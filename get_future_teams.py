import re
import json
import time
import argparse
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

BASE_URL = "https://www.nrl.com"
OUTPUT_DIR = Path("NRL/python files/nrl_outputs/")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_START_SEASON = 2015
DEFAULT_END_SEASON = 2026
DEFAULT_HEADLESS = True

DEFAULT_INITIAL_PAGE_WAIT_MS = 700
DEFAULT_TEAM_LISTS_TAB_WAIT_MS = 900
DEFAULT_REQUEST_SLEEP = 0.4

SPECIAL_ROUND_LABELS = {
    28: "Finals Week 1",
    29: "Finals Week 2",
    30: "Finals Week 3",
    31: "Grand Final",
}
MAX_ROUND_NUMBER = 31

TEAM_SLUG_MAP = {
    "storm": "Melbourne Storm",
    "panthers": "Penrith Panthers",
    "roosters": "Sydney Roosters",
    "broncos": "Brisbane Broncos",
    "sea-eagles": "Manly-Warringah Sea Eagles",
    "rabbitohs": "South Sydney Rabbitohs",
    "knights": "Newcastle Knights",
    "raiders": "Canberra Raiders",
    "warriors": "New Zealand Warriors",
    "sharks": "Cronulla-Sutherland Sharks",
    "eels": "Parramatta Eels",
    "bulldogs": "Canterbury-Bankstown Bulldogs",
    "titans": "Gold Coast Titans",
    "dragons": "St George Illawarra Dragons",
    "dolphins": "Dolphins",
    "cowboys": "North Queensland Cowboys",
    "wests-tigers": "Wests Tigers",
}

TEAM_LIST_OUTPUT_COLUMNS = [
    "season",
    "round_num",
    "round",
    "round_slug",
    "game_url",
    "home_team",
    "away_team",
    "team_side",
    "team",
    "player",
    "number",
    "position",
]


def parse_args():
    parser = argparse.ArgumentParser(description="Scrape latest NRL named team lists for the next round.")
    parser.add_argument("--start-season", type=int, default=DEFAULT_START_SEASON)
    parser.add_argument("--end-season", type=int, default=DEFAULT_END_SEASON)
    parser.add_argument("--season", type=int, default=None, help="Optional fixed season override")
    parser.add_argument("--round-num", type=int, default=None, help="Optional fixed round override")
    parser.add_argument("--headless", action="store_true", default=DEFAULT_HEADLESS)
    parser.add_argument("--show-browser", action="store_true")
    parser.add_argument("--initial-page-wait-ms", type=int, default=DEFAULT_INITIAL_PAGE_WAIT_MS)
    parser.add_argument("--team-lists-tab-wait-ms", type=int, default=DEFAULT_TEAM_LISTS_TAB_WAIT_MS)
    parser.add_argument("--request-sleep", type=float, default=DEFAULT_REQUEST_SLEEP)
    return parser.parse_args()


def normalise_space(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def clean_url(url: str) -> str:
    parsed = urlparse(url)
    cleaned = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    return cleaned.rstrip("/") + "/"


def slug_to_team_name(slug: str) -> str:
    return TEAM_SLUG_MAP.get(slug, slug.replace("-", " ").title())


def derive_teams_from_url(url: str):
    slug = url.rstrip("/").split("/")[-1]
    if "-v-" not in slug:
        return None, None
    home_slug, away_slug = slug.split("-v-")
    return slug_to_team_name(home_slug), slug_to_team_name(away_slug)


def round_label(round_num: int) -> str:
    return SPECIAL_ROUND_LABELS.get(round_num, f"Round {round_num}")


def accept_cookies(page):
    for selector in [
        'button:has-text("Accept")',
        'button:has-text("I Agree")',
        'button:has-text("Allow All")',
        'button:has-text("Accept All")',
    ]:
        try:
            loc = page.locator(selector).first
            if loc.is_visible(timeout=1000):
                loc.click(timeout=1500)
                page.wait_for_timeout(300)
                break
        except Exception:
            pass


def click_named_tab(page, tab_name: str, wait_ms: int):
    selectors = [
        f'[role="tab"]:has-text("{tab_name}")',
        f'button:has-text("{tab_name}")',
        f'a:has-text("{tab_name}")',
        f'text={tab_name}',
    ]
    for selector in selectors:
        try:
            loc = page.locator(selector).first
            if loc.is_visible(timeout=1500):
                loc.click(timeout=2000)
                page.wait_for_timeout(wait_ms)
                return True
        except Exception:
            pass
    return False


def extract_scores_from_page(page):
    try:
        home_loc = page.locator(".match-team__score--home").first
        away_loc = page.locator(".match-team__score--away").first
        home_text = home_loc.inner_text(timeout=2000).strip()
        away_text = away_loc.inner_text(timeout=2000).strip()
        home_score = int(re.search(r"\d+", home_text).group())
        away_score = int(re.search(r"\d+", away_text).group())
        return home_score, away_score
    except Exception:
        return None, None


def get_round_game_urls(page, season: int, round_num: int):
    round_url = f"{BASE_URL}/draw/?competition=111&round={round_num}&season={season}"
    page.goto(round_url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(1200)
    accept_cookies(page)

    raw_links = page.locator("a").evaluate_all(
        """els => els.map(a => a.href).filter(Boolean)"""
    )

    urls = []
    seen = set()
    for href in raw_links:
        if f"/draw/nrl-premiership/{season}/" not in href:
            continue
        if "-v-" not in href:
            continue
        cleaned = clean_url(href)
        if cleaned not in seen:
            seen.add(cleaned)
            urls.append(cleaned)

    return urls


def is_round_fully_completed(page, season: int, round_num: int, args):
    urls = get_round_game_urls(page, season, round_num)
    if not urls:
        return False, []

    all_completed = True
    for url in urls:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(args.initial_page_wait_ms)
            accept_cookies(page)
            home_score, away_score = extract_scores_from_page(page)
            if home_score is None or away_score is None:
                all_completed = False
                break
        except Exception:
            all_completed = False
            break

    return all_completed, urls


def find_latest_completed_round_and_next(page, season: int, args):
    latest_completed = None

    for round_num in range(1, MAX_ROUND_NUMBER + 1):
        completed, urls = is_round_fully_completed(page, season, round_num, args)

        if not urls:
            break

        if completed:
            latest_completed = round_num
        else:
            return latest_completed, round_num

    if latest_completed is None:
        return None, None

    next_round = latest_completed + 1
    if next_round <= MAX_ROUND_NUMBER:
        next_urls = get_round_game_urls(page, season, next_round)
        if next_urls:
            return latest_completed, next_round

    return latest_completed, None


def clean_player_name(name: str) -> str:
    name = normalise_space(name)

    # Remove captain marker
    name = re.sub(r"\bCAPTAIN\b", "", name, flags=re.IGNORECASE)

    # Remove player status text
    name = re.sub(r"\bPLAYER STATUS:\s*[A-Z]+\b", "", name, flags=re.IGNORECASE)

    # Remove weird fragments
    name = re.sub(r"^for\s+.+?\s+At\s*", "", name, flags=re.IGNORECASE)

    # Remove stray punctuation at edges
    name = re.sub(r"^[^\w']+|[^\w']+$", "", name)

    return normalise_space(name)

def is_valid_player_name(name: str) -> bool:
    if not name:
        return False

    bad_patterns = [
        r"^for\s+.+\s+At$",
        r"^PLAYER STATUS",
        r"^FIELD\s*\d*$",
        r"^AT\s+",
    ]

    for pattern in bad_patterns:
        if re.search(pattern, name, flags=re.IGNORECASE):
            return False

    # Require at least first + last name
    if len(name.split()) < 2:
        return False

    return True


def extract_full_name_from_profile(profile):
    """
    Prefer image alt because it contains the full player name.
    Fallback to the visible name block if needed.
    """
    # 1) Best source: image alt
    try:
        img = profile.locator("img.team-list-profile__img").first
        if img.count() > 0:
            alt = img.get_attribute("alt")
            alt = clean_player_name(alt)
            if is_valid_player_name(alt):
                return alt
    except Exception:
        pass

    # 2) Fallback: visible name block
    try:
        name_block = profile.locator(".team-list-profile__name").first
        if name_block.count() > 0:
            text = normalise_space(name_block.inner_text(timeout=1000))
            text = clean_player_name(text)
            if is_valid_player_name(text):
                return text
    except Exception:
        pass

    return None


def normalize_position(position: str) -> str:
    position = normalise_space(position).upper()
    mapping = {
        "FULLBACK": "Fullback",
        "WINGER": "Winger",
        "CENTRE": "Centre",
        "FIVE-EIGHTH": "Five-Eighth",
        "FIVE EIGHTH": "Five-Eighth",
        "HALFBACK": "Halfback",
        "PROP": "Prop",
        "HOOKER": "Hooker",
        "2ND ROW": "2nd Row",
        "SECOND ROW": "2nd Row",
        "LOCK": "Lock",
        "INTERCHANGE": "Interchange",
        "REPLACEMENT": "Replacement",
    }
    return mapping.get(position, position.title())


def parse_numeric(value):
    try:
        return int(str(value).strip())
    except Exception:
        return None


def extract_named_team_lists_dom(page, season: int, round_num: int, game_url: str, home_team: str, away_team: str):
    """
    Parse each Team Lists matchup row directly from the DOM:
    left player card = home
    center block = number + position
    right player card = away
    """
    rows = []

    panel = page.locator("#tabs-match-centre-1").first
    if panel.count() == 0:
        return rows

    matchup_rows = panel.locator(".team-list.team-list--match-centre").all()
    seen_keys = set()

    for matchup in matchup_rows:
        try:
            home_profile = matchup.locator(".team-list-profile--home").first
            away_profile = matchup.locator(".team-list-profile--away").first
            position_block = matchup.locator(".team-list-position").first

            if position_block.count() == 0:
                continue

            # Number block can contain one or two numbers; take first for home, second for away if present.
            number_nodes = position_block.locator(".team-list-position__number").all_inner_texts()
            number_nodes = [normalise_space(x) for x in number_nodes if normalise_space(x)]

            number_home = None
            number_away = None

            if len(number_nodes) >= 1:
                try:
                    number_home = int(number_nodes[0])
                except Exception:
                    number_home = None

            if len(number_nodes) >= 2:
                try:
                    number_away = int(number_nodes[1])
                except Exception:
                    number_away = None

            # If only one number is shown, use it for both sides
            if number_home is not None and number_away is None:
                number_away = number_home

            position_text = position_block.locator(".team-list-position__text").first.inner_text(timeout=1000)
            position = normalize_position(position_text)

            home_player = extract_full_name_from_profile(home_profile) if home_profile.count() > 0 else None
            away_player = extract_full_name_from_profile(away_profile) if away_profile.count() > 0 else None

            if is_valid_player_name(home_player):
                key = ("home", home_player, number_home, position)
                if key not in seen_keys:
                    seen_keys.add(key)
                    rows.append({
                        "season": season,
                        "round_num": round_num,
                        "round": round_label(round_num),
                        "round_slug": f"round-{round_num}",
                        "game_url": game_url,
                        "home_team": home_team,
                        "away_team": away_team,
                        "team_side": "home",
                        "team": home_team,
                        "player": home_player,
                        "number": number_home,
                        "position": position,
                    })

            if is_valid_player_name(away_player):
                key = ("away", away_player, number_away, position)
                if key not in seen_keys:
                    seen_keys.add(key)
                    rows.append({
                        "season": season,
                        "round_num": round_num,
                        "round": round_label(round_num),
                        "round_slug": f"round-{round_num}",
                        "game_url": game_url,
                        "home_team": home_team,
                        "away_team": away_team,
                        "team_side": "away",
                        "team": away_team,
                        "player": away_player,
                        "number": number_away,
                        "position": position,
                    })

        except Exception:
            continue

    return rows


def scrape_match_team_lists(page, url: str, season: int, round_num: int, args):
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(args.initial_page_wait_ms)
    accept_cookies(page)

    home_team, away_team = derive_teams_from_url(url)
    clicked = click_named_tab(page, "Team Lists", args.team_lists_tab_wait_ms)

    player_rows = extract_named_team_lists_dom(
        page=page,
        season=season,
        round_num=round_num,
        game_url=url,
        home_team=home_team,
        away_team=away_team,
    )

    return {
        "team_lists_tab_clicked": clicked,
        "player_rows": player_rows,
    }


def write_outputs(season: int, round_num: int, rows: list[dict]):
    json_path = OUTPUT_DIR / f"nrl_{season}_round_{round_num}_team_lists.json"
    csv_path = OUTPUT_DIR / f"nrl_{season}_round_{round_num}_team_lists.csv"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    df = pd.DataFrame(rows)

    for col in TEAM_LIST_OUTPUT_COLUMNS:
        if col not in df.columns:
            df[col] = None

    df = df[TEAM_LIST_OUTPUT_COLUMNS]
    df = df.sort_values(
        [c for c in ["season", "round_num", "home_team", "away_team", "team_side", "number"] if c in df.columns]
    ).reset_index(drop=True)

    df.to_csv(csv_path, index=False)

    return json_path, csv_path


def main():
    args = parse_args()
    headless = False if args.show_browser else args.headless

    target_season = args.season
    target_round = args.round_num

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            viewport={"width": 1440, "height": 2200},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        if target_season is None:
            for season in range(args.end_season, args.start_season - 1, -1):
                latest_completed, next_round = find_latest_completed_round_and_next(page, season, args)
                if next_round is not None:
                    target_season = season
                    target_round = next_round
                    print(
                        f"Detected target season={target_season}, "
                        f"latest_completed_round={latest_completed}, next_round={target_round}"
                    )
                    break

        if target_season is None or target_round is None:
            browser.close()
            raise RuntimeError("Could not determine target season/round automatically.")

        game_urls = get_round_game_urls(page, target_season, target_round)
        print(f"Season {target_season} | {round_label(target_round)}: found {len(game_urls)} game URLs")

        rows = []
        for i, url in enumerate(game_urls, start=1):
            print(f"[{i}/{len(game_urls)}] Scraping named team lists: {url}")
            try:
                result = scrape_match_team_lists(page, url, target_season, target_round, args)
                player_rows = result["player_rows"]
                rows.extend(player_rows)
                print(f"   -> rows={len(player_rows)}")
            except PlaywrightTimeoutError:
                print("   -> timeout")
            except Exception as e:
                print(f"   -> error: {e}")

            time.sleep(args.request_sleep)

        browser.close()

    json_path, csv_path = write_outputs(target_season, target_round, rows)
    print(f"\nSaved JSON -> {json_path}")
    print(f"Saved CSV  -> {csv_path}")


if __name__ == "__main__":
    main()