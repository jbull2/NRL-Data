"""
rlp_fixtures_and_team_totals_scraper.py

Scrape NRL fixtures/results from RugbyLeagueProject.org and enrich each match
with team totals from the game's Stats page.

This version supports:
- scraping only the latest season (e.g. 2026)
- skipping historical re-scrapes
- rebuilding combined CSV/JSON from local season JSONs
- correctly mapping stats page team totals to fixture home/away teams

Install:
    pip install requests beautifulsoup4 pandas lxml
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.rugbyleagueproject.org"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )
}


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def safe_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    text = clean_text(value).replace(",", "")
    if text == "":
        return None
    try:
        return int(text)
    except ValueError:
        return None


def split_day_time(raw: str) -> tuple[Optional[str], Optional[str]]:
    raw = clean_text(raw)
    if not raw:
        return None, None

    m = re.match(r"^([A-Za-z]{3})\s+(.+)$", raw)
    if m:
        return m.group(1), m.group(2)

    return None, raw


def parse_date_with_carry(
    raw_date: str,
    last_month: Optional[str],
    season: int
) -> tuple[Optional[str], Optional[str], Optional[int], Optional[str]]:
    raw_date = clean_text(raw_date)
    if not raw_date:
        return None, last_month, None, None

    month_map = {
        "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4,
        "May": 5, "Jun": 6, "Jul": 7, "Aug": 8,
        "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12
    }

    m1 = re.match(r"^([A-Za-z]{3})\s+(\d{1,2})$", raw_date)
    if m1:
        month_str = m1.group(1)
        day_num = int(m1.group(2))
        month_num = month_map.get(month_str)
        if month_num:
            return f"{season:04d}-{month_num:02d}-{day_num:02d}", month_str, day_num, month_str

    m2 = re.match(r"^(\d{1,2})$", raw_date)
    if m2 and last_month:
        day_num = int(m2.group(1))
        month_num = month_map.get(last_month)
        if month_num:
            return f"{season:04d}-{month_num:02d}-{day_num:02d}", last_month, day_num, last_month

    return None, last_month, None, None


def extract_game_id(match_url: Optional[str]) -> Optional[int]:
    if not match_url:
        return None
    m = re.search(r"/matches/(\d+)", match_url)
    return int(m.group(1)) if m else None


def normalize_team_name(name: Any) -> str:
    """
    Normalize fixture team names and stats-page team names
    so we can safely map stats to home/away.
    """
    text = clean_text(name).lower()

    replacements = {
        "brisbane broncos": "brisbane",
        "brisbane": "brisbane",

        "canterbury bankstown bulldogs": "canterbury",
        "canterbury": "canterbury",

        "cronulla sutherland sharks": "cronulla",
        "cronulla": "cronulla",

        "gold coast titans": "gold coast",
        "gold coast": "gold coast",

        "manly warringah sea eagles": "manly",
        "manly": "manly",

        "melbourne storm": "melbourne",
        "melbourne": "melbourne",

        "newcastle knights": "newcastle",
        "newcastle": "newcastle",

        "north queensland cowboys": "north qld",
        "north qld": "north qld",

        "parramatta eels": "parramatta",
        "parramatta": "parramatta",

        "penrith panthers": "penrith",
        "penrith": "penrith",

        "south sydney rabbitohs": "south sydney",
        "south sydney": "south sydney",

        "st george illawarra dragons": "st geo illa",
        "st geo illa": "st geo illa",

        "sydney roosters": "sydney",
        "sydney": "sydney",

        "wests tigers": "wests tigers",

        "canberra raiders": "canberra",
        "canberra": "canberra",

        "new zealand warriors": "warriors",
        "warriors": "warriors",

        "the dolphins": "dolphins",
        "dolphins": "dolphins",
    }

    return replacements.get(text, text)


class RLPFixturesAndStatsScraper:
    def __init__(self, sleep_seconds: float = 0.5, timeout: int = 30) -> None:
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.sleep_seconds = sleep_seconds
        self.timeout = timeout

    def get_soup(self, url: str) -> Tuple[BeautifulSoup, str]:
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        return BeautifulSoup(response.text, "lxml"), response.url

    def season_results_url(self, season: int) -> str:
        return f"{BASE_URL}/seasons/nrl-{season}/results.html"

    def scrape_season_fixtures(self, season: int) -> pd.DataFrame:
        url = self.season_results_url(season)
        print(f"\nScraping fixtures for season {season}: {url}")

        soup, _ = self.get_soup(url)
        rows = soup.find_all("tr")

        records: List[Dict[str, Any]] = []
        current_round: Optional[str] = None
        last_month: Optional[str] = None

        for row in rows:
            cols = row.find_all("td")
            row_text = clean_text(row.get_text(" ", strip=True))

            # Check for regular rounds
            if "Round " in row_text and len(cols) <= 1:
                round_match = re.search(r"(Round\s+\d+)", row_text, flags=re.IGNORECASE)
                if round_match:
                    current_round = round_match.group(1).title()
                continue

            # NEW: Check for finals rounds
            finals_patterns = [
                r"(Qualifying Final)",
                r"(Elimination Final)",
                r"(Semi Final)",
                r"(Preliminary Final)",
                r"(Prelim Final)",
                r"(Grand Final)",
                r"(Qual Final)",
            ]
            
            for pattern in finals_patterns:
                if re.search(pattern, row_text, flags=re.IGNORECASE):
                    match = re.search(pattern, row_text, flags=re.IGNORECASE)
                    if match:
                        current_round = match.group(1).title()
                        break

            if not cols:
                continue

            if row_text.startswith("Bye:") or "Bye:" in row_text:
                continue

            if len(cols) < 7:
                continue

            try:
                competition = clean_text(cols[0].get_text(strip=True))
                raw_date = clean_text(cols[1].get_text(strip=True))
                raw_time = clean_text(cols[2].get_text(strip=True))
                home_team = clean_text(cols[3].get_text(strip=True))
                home_score = safe_int(cols[4].get_text(strip=True))
                away_team = clean_text(cols[5].get_text(strip=True))
                away_score = safe_int(cols[6].get_text(strip=True))
                referee = clean_text(cols[7].get_text(strip=True))
                venue = clean_text(cols[8].get_text(strip=True))
                attendance = safe_int(cols[9].get_text(strip=True))

                full_date, last_month, day_num, month_str = parse_date_with_carry(
                    raw_date, last_month, season
                )
                day_name, kickoff_time = split_day_time(raw_time)

                match_url = None
                link_tag = cols[-1].find("a", href=True)
                if link_tag:
                    match_url = urljoin(BASE_URL, link_tag["href"])

                game_id = extract_game_id(match_url)

                winner = None
                margin = None
                if home_score is not None and away_score is not None:
                    margin = home_score - away_score
                    if home_score > away_score:
                        winner = home_team
                    elif away_score > home_score:
                        winner = away_team
                    else:
                        winner = "Draw"

                if home_team and away_team:
                    records.append({
                        "season": season,
                        "competition": competition,
                        "round": current_round,
                        "raw_date": raw_date,
                        "month": month_str,
                        "day_of_month": day_num,
                        "date": full_date,
                        "raw_time": raw_time,
                        "day_name": day_name,
                        "kickoff_time": kickoff_time,
                        "home_team": home_team,
                        "away_team": away_team,
                        "home_score": home_score,
                        "away_score": away_score,
                        "winner": winner,
                        "margin": margin,
                        "referee": referee if referee else None,
                        "venue": venue if venue else None,
                        "attendance": attendance,
                        "match_url": match_url,
                        "game_id": game_id,
                        "source": "rugbyleagueproject.org",
                    })

            except Exception as e:
                print(f"Error parsing fixture row for season {season}: {e}")
                print(f"Row text: {row_text}")

        df = pd.DataFrame(records)

        if not df.empty:
            preferred_cols = [
                "season", "competition", "round", "date", "raw_date", "month", "day_of_month",
                "day_name", "kickoff_time", "raw_time",
                "home_team", "away_team", "home_score", "away_score", "winner", "margin",
                "referee", "venue", "attendance", "match_url", "game_id", "source"
            ]
            df = df[[c for c in preferred_cols if c in df.columns]]

        print(f"Finished fixtures for {season}: {len(df)} matches")
        print(f"  Rounds found: {df['round'].unique() if not df.empty else 'None'}")
        
        return df

    def find_stats_url_from_match_page(self, match_url: str) -> Optional[str]:
        soup, final_url = self.get_soup(match_url)

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            text = clean_text(a.get_text(" ", strip=True)).lower()

            if text == "stats":
                return urljoin(final_url, href)

            if href.lower().endswith("stats.html"):
                return urljoin(final_url, href)

        if final_url.endswith("/summary.html"):
            return final_url.replace("/summary.html", "/stats.html")

        if "/seasons/" in final_url and not final_url.endswith("/stats.html"):
            if final_url.endswith("/"):
                return urljoin(final_url, "stats.html")
            return final_url.rstrip("/") + "/stats.html"

        return None

    def parse_team_totals_from_stats_page(
        self,
        stats_url: str,
        expected_home_team: Optional[str] = None,
        expected_away_team: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Parse the Totals row for both teams from the stats page.

        Only headings that match the expected fixture home/away teams
        are accepted, which prevents capturing headings like:
        - Round 1
        - Full match title
        """
        soup, final_stats_url = self.get_soup(stats_url)

        expected_home_norm = normalize_team_name(expected_home_team)
        expected_away_norm = normalize_team_name(expected_away_team)

        result = {
            "stats_url": final_stats_url,
            "stats_team_sections": []
        }

        team_sections: List[Dict[str, Any]] = []

        for heading in soup.find_all(["h2", "h3", "h4"]):
            team_name = clean_text(heading.get_text(" ", strip=True))
            if not team_name:
                continue

            team_norm = normalize_team_name(team_name)

            # Only keep real team headings that match fixture teams
            if team_norm not in {expected_home_norm, expected_away_norm}:
                continue

            table = heading.find_next("table")
            if table is None:
                continue

            totals_row_cells = None
            for tr in table.find_all("tr"):
                row_cells = [
                    clean_text(td.get_text(" ", strip=True))
                    for td in tr.find_all(["td", "th"])
                ]
                if row_cells and row_cells[0].lower() == "totals":
                    totals_row_cells = row_cells
                    break

            if totals_row_cells is None:
                continue

            numeric_values: List[int] = []
            for cell in totals_row_cells[1:]:
                val = safe_int(cell)
                if val is not None:
                    numeric_values.append(val)

            if len(numeric_values) < 4:
                continue

            section = {
                "team_name": team_name,
                "team_name_normalized": team_norm,
                "tries": numeric_values[0],
                "goals": numeric_values[1],
                "field_goals": numeric_values[2],
                "points": numeric_values[3],
            }

            if not any(s["team_name_normalized"] == team_norm for s in team_sections):
                team_sections.append(section)

            if len(team_sections) == 2:
                break

        result["stats_team_sections"] = team_sections
        return result

    def enrich_fixtures_with_team_totals(self, fixtures_df: pd.DataFrame) -> pd.DataFrame:
        if fixtures_df.empty:
            return fixtures_df.copy()

        enriched_records = []
        total_games = len(fixtures_df)

        for idx, row in fixtures_df.iterrows():
            base = row.to_dict()
            match_url = row.get("match_url")

            stats_data = {
                "stats_url": None,
                "stats_home_team": None,
                "stats_home_tries": None,
                "stats_home_goals": None,
                "stats_home_field_goals": None,
                "stats_home_points": None,
                "stats_away_team": None,
                "stats_away_tries": None,
                "stats_away_goals": None,
                "stats_away_field_goals": None,
                "stats_away_points": None,
            }

            print(f"[{idx + 1}/{total_games}] Enriching game_id={row.get('game_id')}")

            try:
                if match_url:
                    stats_url = self.find_stats_url_from_match_page(match_url)
                    if stats_url:
                        parsed = self.parse_team_totals_from_stats_page(
                            stats_url=stats_url,
                            expected_home_team=row.get("home_team"),
                            expected_away_team=row.get("away_team"),
                        )
                        stats_data["stats_url"] = parsed.get("stats_url")

                        sections = parsed.get("stats_team_sections", [])
                        home_norm = normalize_team_name(row.get("home_team"))
                        away_norm = normalize_team_name(row.get("away_team"))

                        for section in sections:
                            team_norm = section.get("team_name_normalized")

                            if team_norm == home_norm:
                                stats_data["stats_home_team"] = section.get("team_name")
                                stats_data["stats_home_tries"] = section.get("tries")
                                stats_data["stats_home_goals"] = section.get("goals")
                                stats_data["stats_home_field_goals"] = section.get("field_goals")
                                stats_data["stats_home_points"] = section.get("points")

                            elif team_norm == away_norm:
                                stats_data["stats_away_team"] = section.get("team_name")
                                stats_data["stats_away_tries"] = section.get("tries")
                                stats_data["stats_away_goals"] = section.get("goals")
                                stats_data["stats_away_field_goals"] = section.get("field_goals")
                                stats_data["stats_away_points"] = section.get("points")
                    else:
                        print(f"No stats URL found for match_url={match_url}")
            except Exception as e:
                print(f"Failed to enrich match_url={match_url}: {e}")

            base.update(stats_data)
            enriched_records.append(base)

            time.sleep(self.sleep_seconds)

        df = pd.DataFrame(enriched_records)

        if not df.empty:
            df["home_tries"] = df["stats_home_tries"]
            df["home_goals"] = df["stats_home_goals"]
            df["home_field_goals"] = df["stats_home_field_goals"]
            df["home_points_from_stats"] = df["stats_home_points"]

            df["away_tries"] = df["stats_away_tries"]
            df["away_goals"] = df["stats_away_goals"]
            df["away_field_goals"] = df["stats_away_field_goals"]
            df["away_points_from_stats"] = df["stats_away_points"]

            df["home_points_match"] = df["home_score"] == df["home_points_from_stats"]
            df["away_points_match"] = df["away_score"] == df["away_points_from_stats"]

        return df


def load_existing_season_json(json_path: Path) -> pd.DataFrame:
    if not json_path.exists():
        return pd.DataFrame()

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return pd.DataFrame(data)


def save_season_outputs(df: pd.DataFrame, out_dir: Path, season: int) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / f"rlp_nrl_fixtures_team_totals_{season}.csv"
    json_path = out_dir / f"rlp_nrl_fixtures_team_totals_{season}.json"

    df.to_csv(csv_path, index=False, encoding="utf-8")
    df.to_json(json_path, orient="records", indent=2, force_ascii=False)

    print(f"Saved CSV:  {csv_path}")
    print(f"Saved JSON: {json_path}")


def save_combined_outputs(df_all: pd.DataFrame, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / "rlp_nrl_fixtures_team_totals_all.csv"
    json_path = out_dir / "rlp_nrl_fixtures_team_totals_all.json"

    df_all.to_csv(csv_path, index=False, encoding="utf-8")
    df_all.to_json(json_path, orient="records", indent=2, force_ascii=False)

    print(f"Saved combined CSV:  {csv_path}")
    print(f"Saved combined JSON: {json_path}")


if __name__ == "__main__":
    OUTPUT_ROOT = Path("../data/NRL")

    # --------------------------------------------------
    # CONFIG
    # --------------------------------------------------
    LATEST_SEASON_ONLY = True
    LATEST_SEASON = 2026

    # Rebuild combined all-seasons file from existing JSONs on disk
    REBUILD_COMBINED_FROM_EXISTING_JSONS = True

    HISTORICAL_START_YEAR = 2015
    HISTORICAL_END_YEAR = 2026

    scraper = RLPFixturesAndStatsScraper(sleep_seconds=0.3, timeout=30)

    season_frames: List[pd.DataFrame] = []

    # --------------------------------------------------
    # SCRAPE SEASONS
    # --------------------------------------------------
    if LATEST_SEASON_ONLY:
        seasons_to_scrape = [LATEST_SEASON]
    else:
        seasons_to_scrape = list(range(HISTORICAL_START_YEAR, HISTORICAL_END_YEAR + 1))

    for season in seasons_to_scrape:
        try:
            print(f"\n=== Processing season {season} ===")
            df = scraper.scrape_season_fixtures(season)

            if df.empty:
                print(f"No data returned for {season}")
                continue

            df = scraper.enrich_fixtures_with_team_totals(df)
            save_season_outputs(df, OUTPUT_ROOT / str(season), season)
            season_frames.append(df)

        except requests.HTTPError as e:
            print(f"HTTP error for season {season}: {e}")
        except Exception as e:
            print(f"Unexpected error for season {season}: {e}")

    # --------------------------------------------------
    # SAVE COMBINED FILE FROM FRESH SCRAPE
    # --------------------------------------------------
    if season_frames:
        df_all = pd.concat(season_frames, ignore_index=True)
        save_combined_outputs(df_all, OUTPUT_ROOT)

        print("\nCombined summary:")
        print(df_all.groupby("season").size())
    else:
        print("No season data was scraped.")

    # --------------------------------------------------
    # OPTIONAL: rebuild combined all-seasons file from existing JSONs
    # --------------------------------------------------
    if REBUILD_COMBINED_FROM_EXISTING_JSONS:
        combined_frames: List[pd.DataFrame] = []

        for season in range(HISTORICAL_START_YEAR, HISTORICAL_END_YEAR + 1):
            season_dir = OUTPUT_ROOT / str(season)
            json_path = season_dir / f"rlp_nrl_fixtures_team_totals_{season}.json"

            df_existing = load_existing_season_json(json_path)
            if df_existing is not None and not df_existing.empty:
                combined_frames.append(df_existing)
            else:
                print(f"Missing or empty JSON for season {season}: {json_path}")

        if combined_frames:
            df_all = pd.concat(combined_frames, ignore_index=True)
            save_combined_outputs(df_all, OUTPUT_ROOT)

            print("\nCombined summary from existing JSONs:")
            print(df_all.groupby("season").size())
        else:
            print("No existing season JSONs found to combine.")

    print("\nDone.")