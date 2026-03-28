import re
import time
import json
import argparse
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

BASE_URL = "https://www.nrl.com"

# =========================================================
# DEFAULT CONFIG
# =========================================================
DEFAULT_START_SEASON = 2015
DEFAULT_END_SEASON = 2026

DEFAULT_HEADLESS = True
DEFAULT_FORCE_RESCRAPE = False

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "nrl_outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Based on your benchmark baseline
DEFAULT_INITIAL_PAGE_WAIT_MS = 700
DEFAULT_TEAM_TAB_WAIT_MS = 800
DEFAULT_PLAYER_TAB_WAIT_MS = 800
DEFAULT_AWAY_TOGGLE_WAIT_MS = 800

DEFAULT_REQUEST_SLEEP = 0.5
DEFAULT_ROUND_SLEEP = 0.75
DEFAULT_SEASON_SLEEP = 0.75
DEFAULT_EMPTY_ROUND_STOP = 2

SPECIAL_ROUND_LABELS = {
    28: "Finals Week 1",
    29: "Finals Week 2",
    30: "Finals Week 3",
    31: "Grand Final",
}
MAX_ROUND_NUMBER = 31

# =========================================================
# TEAM STAT SCHEMA
# =========================================================
TEAM_STAT_MAP = {
    "POSSESSION %": "possession_pct",
    "TIME IN POSSESSION": "time_in_possession",
    "COMPLETION RATE": "completion_rate",
    "ALL RUNS": "all_runs",
    "ALL RUN METRES": "run_metres",
    "POST CONTACT METRES": "post_contact_metres",
    "LINE BREAKS": "line_breaks",
    "TACKLE BREAKS": "tackle_breaks",
    "AVERAGE SET DISTANCE": "avg_set_distance",
    "KICK RETURN METRES": "kick_return_metres",
    "AVERAGE PLAY THE BALL SPEED": "avg_play_the_ball_speed",
    "OFFLOADS": "offloads",
    "RECEIPTS": "receipts",
    "TOTAL PASSES": "total_passes",
    "DUMMY PASSES": "dummy_passes",
    "KICKS": "kicks",
    "KICKING METRES": "kicking_metres",
    "FORCED DROP OUTS": "forced_drop_outs",
    "KICK DEFUSAL %": "kick_defusal_pct",
    "BOMBS": "bombs",
    "GRUBBERS": "grubbers",
    "EFFECTIVE TACKLE %": "effective_tackle_pct",
    "TACKLES MADE": "tackles_made",
    "MISSED TACKLES": "missed_tackles",
    "INTERCEPTS": "intercepts",
    "INEFFECTIVE TACKLES": "ineffective_tackles",
    "ERRORS": "errors",
    "PENALTIES CONCEDED": "penalties_conceded",
    "RUCK INFRINGEMENTS": "ruck_infringements",
    "INSIDE 10 METRES": "inside_10_metres",
    "ON REPORTS": "on_reports",
    "INTERCHANGES USED": "interchanges_used",
}

TEAM_STAT_ALIASES = {
    "POSSESSION %": ["POSSESSION %", "POSSESSION"],
    "TIME IN POSSESSION": ["TIME IN POSSESSION"],
    "COMPLETION RATE": ["COMPLETION RATE"],
    "ALL RUNS": ["ALL RUNS"],
    "ALL RUN METRES": ["ALL RUN METRES"],
    "POST CONTACT METRES": ["POST CONTACT METRES"],
    "LINE BREAKS": ["LINE BREAKS"],
    "TACKLE BREAKS": ["TACKLE BREAKS"],
    "AVERAGE SET DISTANCE": ["AVERAGE SET DISTANCE"],
    "KICK RETURN METRES": ["KICK RETURN METRES"],
    "AVERAGE PLAY THE BALL SPEED": ["AVERAGE PLAY THE BALL SPEED"],
    "OFFLOADS": ["OFFLOADS"],
    "RECEIPTS": ["RECEIPTS"],
    "TOTAL PASSES": ["TOTAL PASSES"],
    "DUMMY PASSES": ["DUMMY PASSES"],
    "KICKS": ["KICKS"],
    "KICKING METRES": ["KICKING METRES"],
    "FORCED DROP OUTS": ["FORCED DROP OUTS"],
    "KICK DEFUSAL %": ["KICK DEFUSAL %", "KICK DEFUSAL"],
    "BOMBS": ["BOMBS"],
    "GRUBBERS": ["GRUBBERS"],
    "EFFECTIVE TACKLE %": ["EFFECTIVE TACKLE %", "EFFECTIVE TACKLE"],
    "TACKLES MADE": ["TACKLES MADE"],
    "MISSED TACKLES": ["MISSED TACKLES"],
    "INTERCEPTS": ["INTERCEPTS"],
    "INEFFECTIVE TACKLES": ["INEFFECTIVE TACKLES"],
    "ERRORS": ["ERRORS"],
    "PENALTIES CONCEDED": ["PENALTIES CONCEDED"],
    "RUCK INFRINGEMENTS": ["RUCK INFRINGEMENTS"],
    "INSIDE 10 METRES": ["INSIDE 10 METRES"],
    "ON REPORTS": ["ON REPORTS"],
    "INTERCHANGES USED": ["INTERCHANGES USED"],
}

TEAM_STAT_CANONICAL_ORDER = list(TEAM_STAT_ALIASES.keys())

# =========================================================
# PLAYER STAT SCHEMA
# =========================================================
PLAYER_STAT_HEADERS = [
    "points",
    "tries",
    "conversions",
    "conversion_attempts",
    "penalty_goals",
    "goal_conversion_rate",
    "one_point_field_goals",
    "two_point_field_goals",
    "total_points",
    "all_runs",
    "all_run_metres",
    "kick_return_metres",
    "post_contact_metres",
    "line_breaks",
    "line_break_assists",
    "try_assists",
    "line_engaged_runs",
    "tackle_breaks",
    "hit_ups",
    "play_the_ball",
    "avg_play_the_ball_speed",
    "dummy_half_runs",
    "dummy_half_run_metres",
    "one_on_one_steal",
    "offloads",
    "dummy_passes",
    "passes",
    "receipts",
    "passes_to_run_ratio",
    "tackle_efficiency",
    "tackles_made",
    "missed_tackles",
    "ineffective_tackles",
    "intercepts",
    "kicks_defused",
    "kicks",
    "kicking_metres",
    "forced_drop_outs",
    "bomb_kicks",
    "grubbers",
    "kick_40_20",
    "kick_20_40",
    "cross_field_kicks",
    "kicked_dead",
    "errors",
    "handling_errors",
    "one_on_one_lost",
    "penalties",
    "ruck_infringements",
    "inside_10_metres",
    "on_report",
    "sin_bins",
    "send_offs",
    "stint_one",
    "stint_two",
]

PLAYER_START_RE = re.compile(
    r"(?P<player>[A-Z][A-Za-z'.\-]+(?:\s+[A-Z][A-Za-z'.\-]+)+)\s+"
    r"(?P<number>\d+)\s+"
    r"(?P<position>Fullback|Winger|Centre|Halfback|Hooker|Prop|2nd Row|Lock|Interchange|Replacement|Five-Eighth)\s+"
    r"(?P<mins>\d{1,2}:\d{2}|-)"
)

# =========================================================
# TEAM MAPS
# =========================================================
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
}

TEAM_SECTION_LABELS = {
    "Melbourne Storm": ["Storm"],
    "Penrith Panthers": ["Panthers"],
    "Sydney Roosters": ["Roosters"],
    "Brisbane Broncos": ["Broncos"],
    "Manly-Warringah Sea Eagles": ["Sea Eagles", "Sea-Eagles"],
    "South Sydney Rabbitohs": ["Rabbitohs"],
    "Newcastle Knights": ["Knights"],
    "Canberra Raiders": ["Raiders"],
    "New Zealand Warriors": ["Warriors"],
    "Cronulla-Sutherland Sharks": ["Sharks"],
    "Parramatta Eels": ["Eels"],
    "Canterbury-Bankstown Bulldogs": ["Bulldogs"],
    "Gold Coast Titans": ["Titans"],
    "St George Illawarra Dragons": ["Dragons", "St George Illawarra Dragons"],
    "Dolphins": ["Dolphins"],
    "North Queensland Cowboys": ["Cowboys"],
}

# =========================================================
# OUTPUT SCHEMA
# =========================================================
TEAM_BASE_COLUMNS = [
    "season",
    "round_num",
    "round",
    "round_slug",
    "url",
    "home_team",
    "away_team",
    "home_score",
    "away_score",
    "scrape_status",
]

TEAM_DYNAMIC_COLUMNS = []
for canonical_label in TEAM_STAT_CANONICAL_ORDER:
    key = TEAM_STAT_MAP[canonical_label]
    TEAM_DYNAMIC_COLUMNS.extend([f"home_{key}", f"away_{key}"])

TEAM_EXTRA_COLUMNS = [
    "home_completion_rate_made_attempted",
    "away_completion_rate_made_attempted",
]

TEAM_OUTPUT_COLUMNS = TEAM_BASE_COLUMNS + TEAM_DYNAMIC_COLUMNS + TEAM_EXTRA_COLUMNS

PLAYER_BASE_COLUMNS = [
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
    "mins_played",
]

PLAYER_OUTPUT_COLUMNS = PLAYER_BASE_COLUMNS + PLAYER_STAT_HEADERS


# =========================================================
# ARGPARSE
# =========================================================
def parse_args():
    parser = argparse.ArgumentParser(description="Scrape NRL seasons to season JSON files.")
    parser.add_argument("--start-season", type=int, default=DEFAULT_START_SEASON)
    parser.add_argument("--end-season", type=int, default=DEFAULT_END_SEASON)
    parser.add_argument("--headless", action="store_true", default=DEFAULT_HEADLESS)
    parser.add_argument("--show-browser", action="store_true", help="Run with visible browser")
    parser.add_argument("--force-rescrape", action="store_true", default=DEFAULT_FORCE_RESCRAPE)
    parser.add_argument("--initial-page-wait-ms", type=int, default=DEFAULT_INITIAL_PAGE_WAIT_MS)
    parser.add_argument("--team-tab-wait-ms", type=int, default=DEFAULT_TEAM_TAB_WAIT_MS)
    parser.add_argument("--player-tab-wait-ms", type=int, default=DEFAULT_PLAYER_TAB_WAIT_MS)
    parser.add_argument("--away-toggle-wait-ms", type=int, default=DEFAULT_AWAY_TOGGLE_WAIT_MS)
    parser.add_argument("--request-sleep", type=float, default=DEFAULT_REQUEST_SLEEP)
    parser.add_argument("--round-sleep", type=float, default=DEFAULT_ROUND_SLEEP)
    parser.add_argument("--season-sleep", type=float, default=DEFAULT_SEASON_SLEEP)
    parser.add_argument("--empty-round-stop", type=int, default=DEFAULT_EMPTY_ROUND_STOP)
    parser.add_argument("--write-csv", action="store_true", help="Also write CSV outputs")
    parser.add_argument(
        "--force-round",
        type=int,
        nargs="+",
        metavar="ROUND",
        default=None,
        help="Force re-scrape specific round number(s) even if already saved. "
             "E.g. --force-round 4  or  --force-round 3 4",
    )
    return parser.parse_args()


# =========================================================
# PATH HELPERS
# =========================================================
def team_json_path(season: int) -> Path:
    return OUTPUT_DIR / f"nrl_{season}_team_gamelogs.json"


def player_json_path(season: int) -> Path:
    return OUTPUT_DIR / f"nrl_{season}_player_gamelogs.json"


def team_csv_path(season: int) -> Path:
    return OUTPUT_DIR / f"nrl_{season}_team_gamelogs.csv"


def player_csv_path(season: int) -> Path:
    return OUTPUT_DIR / f"nrl_{season}_player_gamelogs.csv"


def season_already_scraped(season: int) -> bool:
    team_json = team_json_path(season)
    player_json = player_json_path(season)

    team_csv = team_csv_path(season)
    player_csv = player_csv_path(season)

    # First check JSON files
    if team_json.exists() and player_json.exists():
        try:
            if team_json.stat().st_size > 0 and player_json.stat().st_size > 0:
                with open(team_json, "r", encoding="utf-8") as f:
                    team_data = json.load(f)

                with open(player_json, "r", encoding="utf-8") as f:
                    player_data = json.load(f)

                if bool(team_data) and bool(player_data):
                    return True
        except Exception:
            pass

    # Fallback check CSV files
    if team_csv.exists() and player_csv.exists():
        try:
            if team_csv.stat().st_size > 0 and player_csv.stat().st_size > 0:
                team_df = pd.read_csv(team_csv, nrows=5)
                player_df = pd.read_csv(player_csv, nrows=5)

                if not team_df.empty and not player_df.empty:
                    return True
        except Exception:
            pass

    return False

def get_missing_rounds_for_season(season: int):
    """
    Check existing JSON first, then CSV fallback, and return which round numbers
    from 1..31 are still missing for the season.

    Returns:
        missing_rounds: sorted list[int]
    """
    expected_rounds = set(range(1, 32))  # 1..31

    def extract_rounds_from_df(df: pd.DataFrame) -> set[int]:
        if df.empty or "round_num" not in df.columns:
            return set()
        rounds = pd.to_numeric(df["round_num"], errors="coerce").dropna().astype(int)
        return set(rounds.unique())

    # Prefer JSON
    team_json = team_json_path(season)
    player_json = player_json_path(season)

    if team_json.exists() and player_json.exists():
        try:
            if team_json.stat().st_size > 0 and player_json.stat().st_size > 0:
                with open(team_json, "r", encoding="utf-8") as f:
                    team_data = json.load(f)
                with open(player_json, "r", encoding="utf-8") as f:
                    player_data = json.load(f)

                team_df = pd.DataFrame(team_data)
                player_df = pd.DataFrame(player_data)

                team_rounds = extract_rounds_from_df(team_df)
                player_rounds = extract_rounds_from_df(player_df)

                # only count a round as complete if it exists in BOTH outputs
                completed_rounds = team_rounds & player_rounds
                missing_rounds = sorted(expected_rounds - completed_rounds)
                return missing_rounds
        except Exception:
            pass

    # Fallback to CSV
    team_csv = team_csv_path(season)
    player_csv = player_csv_path(season)

    if team_csv.exists() and player_csv.exists():
        try:
            if team_csv.stat().st_size > 0 and player_csv.stat().st_size > 0:
                team_df = pd.read_csv(team_csv)
                player_df = pd.read_csv(player_csv)

                team_rounds = extract_rounds_from_df(team_df)
                player_rounds = extract_rounds_from_df(player_df)

                completed_rounds = team_rounds & player_rounds
                missing_rounds = sorted(expected_rounds - completed_rounds)
                return missing_rounds
        except Exception:
            pass

    return sorted(expected_rounds)

# =========================================================
# ROUND CONFIG
# =========================================================
def get_round_configs():
    rounds = []
    for round_num in range(1, MAX_ROUND_NUMBER + 1):
        round_slug = f"round-{round_num}"
        round_label = SPECIAL_ROUND_LABELS.get(round_num, f"Round {round_num}")
        rounds.append((round_num, round_slug, round_label))
    return rounds


# =========================================================
# GENERAL HELPERS
# =========================================================
def normalise_space(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def normalize_numeric_commas(text: str) -> str:
    if not text:
        return text
    return re.sub(r"(?<=\d),(?=\d)", "", text)


def clean_url(url: str) -> str:
    parsed = urlparse(url)
    cleaned = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    return cleaned.rstrip("/") + "/"


def is_game_url(url: str, season: int, round_slug: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")

    if not path.startswith(f"/draw/nrl-premiership/{season}/{round_slug}"):
        return False

    parts = [p for p in path.split("/") if p]
    if len(parts) < 5:
        return False

    return "-v-" in parts[-1]


def parse_numericish(value):
    if value is None:
        return None

    value = str(value).strip()
    if value in {"", "-", "nan"}:
        return None

    value = re.sub(r"(?<=\d),(?=\d)", "", value)

    if re.fullmatch(r"\d{1,2}:\d{2}", value):
        return value
    if re.fullmatch(r"\d+\s*/\s*\d+", value):
        return value.replace(" ", "")
    if re.fullmatch(r"-?\d+(?:\.\d+)?%", value):
        return float(value.replace("%", ""))
    if re.fullmatch(r"-?\d+(?:\.\d+)?s", value.lower()):
        return float(value[:-1])
    if re.fullmatch(r"-?\d+(?:\.\d+)?", value):
        num = float(value)
        return int(num) if num.is_integer() else num

    return value


def find_value_tokens(segment: str):
    segment = normalize_numeric_commas(segment)
    token_re = re.compile(r"\d{1,2}:\d{2}|\d+/\d+|\d+(?:\.\d+)?%?s?")
    return token_re.findall(segment)


def slug_to_team_name(slug: str) -> str:
    return TEAM_SLUG_MAP.get(slug, slug.replace("-", " ").title())


def derive_teams_from_url(url: str):
    slug = url.rstrip("/").split("/")[-1]
    if "-v-" not in slug:
        return None, None
    home_slug, away_slug = slug.split("-v-")
    return slug_to_team_name(home_slug), slug_to_team_name(away_slug)


def team_to_section_labels(team_name: str):
    return TEAM_SECTION_LABELS.get(team_name, [team_name])


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


def get_body_text(page):
    text = page.locator("body").inner_text(timeout=8000)
    return normalize_numeric_commas(text)


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


def click_player_team_selector(page, team_name: str, team_labels: list[str], wait_ms: int):
    candidates = [team_name] + team_labels
    selectors = []

    for name in candidates:
        selectors.extend([
            f'#tabs-match-centre-4 button:has-text("{name}")',
            f'#tabs-match-centre-4 [role="tab"]:has-text("{name}")',
            f'#tabs-match-centre-4 a:has-text("{name}")',
            f'#tabs-match-centre-4 text="{name}"',
        ])

    for selector in selectors:
        try:
            loc = page.locator(selector).first
            if loc.count() > 0 and loc.is_visible(timeout=1200):
                loc.click(timeout=1800)
                page.wait_for_timeout(wait_ms)
                return True
        except Exception:
            pass

    return False


# =========================================================
# TEAM STATS PARSING
# =========================================================
def extract_team_stat_block(full_text: str) -> str:
    text = normalise_space(full_text)

    start_candidates = []
    for canonical in ["POSSESSION %", "COMPLETION RATE", "ALL RUNS"]:
        for alias in TEAM_STAT_ALIASES.get(canonical, [canonical]):
            idx = text.find(alias)
            if idx != -1:
                start_candidates.append(idx)

    if not start_candidates:
        return ""

    start = min(start_candidates)

    end_candidates = [
        text.find("Top Performing Players", start),
        text.find("Player Stats", start),
    ]
    end_candidates = [x for x in end_candidates if x != -1]
    end = min(end_candidates) if end_candidates else len(text)

    return text[start:end]


def build_team_label_positions(block: str):
    positions = []

    for canonical_label, aliases in TEAM_STAT_ALIASES.items():
        found = None
        for alias in aliases:
            idx = block.find(alias)
            if idx != -1:
                if found is None or idx < found[0]:
                    found = (idx, canonical_label, alias)
        if found is not None:
            positions.append(found)

    positions.sort(key=lambda x: x[0])
    return positions


def split_team_stat_segments(block: str):
    positions = build_team_label_positions(block)
    segments = {}

    for i, (idx, canonical_label, matched_alias) in enumerate(positions):
        next_idx = positions[i + 1][0] if i + 1 < len(positions) else len(block)
        segments[canonical_label] = {
            "segment": normalise_space(block[idx:next_idx]),
            "matched_alias": matched_alias,
        }

    return segments


def strip_label_from_segment(segment: str, matched_alias: str) -> str:
    if segment.startswith(matched_alias):
        return normalise_space(segment[len(matched_alias):])
    return segment


def parse_team_stat_segment(canonical_label: str, segment: str, matched_alias: str):
    value_area = strip_label_from_segment(segment, matched_alias)
    tokens = find_value_tokens(value_area)

    if canonical_label == "COMPLETION RATE":
        pct_tokens = [t for t in tokens if "%" in t]
        frac_tokens = [t for t in tokens if "/" in t]
        if len(pct_tokens) >= 2 and len(frac_tokens) >= 2:
            return {
                "home_completion_rate": parse_numericish(pct_tokens[0]),
                "home_completion_rate_made_attempted": parse_numericish(frac_tokens[0]),
                "away_completion_rate": parse_numericish(pct_tokens[1]),
                "away_completion_rate_made_attempted": parse_numericish(frac_tokens[1]),
            }
        return {}

    if canonical_label == "POSSESSION %":
        pct_tokens = [t for t in tokens if "%" in t]
        if len(pct_tokens) >= 2:
            return {
                "home_possession_pct": parse_numericish(pct_tokens[0]),
                "away_possession_pct": parse_numericish(pct_tokens[1]),
            }
        return {}

    if canonical_label == "TIME IN POSSESSION":
        time_tokens = [t for t in tokens if re.fullmatch(r"\d{1,2}:\d{2}", t)]
        if len(time_tokens) >= 2:
            return {
                "home_time_in_possession": time_tokens[0],
                "away_time_in_possession": time_tokens[1],
            }
        return {}

    key = TEAM_STAT_MAP[canonical_label]
    if len(tokens) >= 2:
        return {
            f"home_{key}": parse_numericish(tokens[0]),
            f"away_{key}": parse_numericish(tokens[1]),
        }

    return {}


def extract_team_stats(full_text: str):
    block = extract_team_stat_block(full_text)
    if not block:
        return {}

    segments = split_team_stat_segments(block)
    out = {}

    for canonical_label, info in segments.items():
        out.update(
            parse_team_stat_segment(
                canonical_label=canonical_label,
                segment=info["segment"],
                matched_alias=info["matched_alias"],
            )
        )

    return out


# =========================================================
# PLAYER STATS PARSING
# =========================================================
def clean_player_section(section_text: str):
    text = normalise_space(section_text)

    cut_idx = -1
    for marker in ["Stint Two", "Send Offs"]:
        idx = text.find(marker)
        if idx != -1:
            cut_idx = max(cut_idx, idx + len(marker))

    if cut_idx != -1:
        text = normalise_space(text[cut_idx:])

    first_player = PLAYER_START_RE.search(text)
    if first_player:
        text = text[first_player.start():]

    return text


def parse_player_rows_from_section(section_text: str):
    text = clean_player_section(section_text)
    starts = list(PLAYER_START_RE.finditer(text))
    rows = []

    for i, m in enumerate(starts):
        start = m.start()
        end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        row_text = normalise_space(text[start:end])

        player = m.group("player")
        number = parse_numericish(m.group("number"))
        position = m.group("position")
        mins = m.group("mins")

        after_header = normalise_space(row_text[m.end() - start:])
        tokens = after_header.split()

        if len(tokens) < len(PLAYER_STAT_HEADERS):
            tokens = tokens + [None] * (len(PLAYER_STAT_HEADERS) - len(tokens))
        else:
            tokens = tokens[:len(PLAYER_STAT_HEADERS)]

        stat_map = {
            col: parse_numericish(tok)
            for col, tok in zip(PLAYER_STAT_HEADERS, tokens)
        }

        rows.append({
            "player": player,
            "number": number,
            "position": position,
            "mins_played": mins,
            **stat_map
        })

    return rows


def extract_player_stats_from_single_team_text(full_text: str, game_meta: dict, team_side: str):
    team_name = game_meta["home_team"] if team_side == "home" else game_meta["away_team"]
    rows = parse_player_rows_from_section(full_text)

    player_rows = []
    for row in rows:
        player_rows.append({
            "season": game_meta["season"],
            "round": game_meta["round"],
            "round_slug": game_meta["round_slug"],
            "round_num": game_meta["round_num"],
            "game_url": game_meta["url"],
            "home_team": game_meta["home_team"],
            "away_team": game_meta["away_team"],
            "team_side": team_side,
            "team": team_name,
            **row
        })

    return player_rows


# =========================================================
# DATAFRAME HELPERS
# =========================================================
def dedupe_team_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    subset = ["season", "round_slug", "home_team", "away_team", "url"]
    subset = [c for c in subset if c in df.columns]
    return df.drop_duplicates(subset=subset, keep="last").reset_index(drop=True)


def dedupe_player_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    subset = ["season", "round_slug", "home_team", "away_team", "team_side", "team", "player", "number"]
    subset = [c for c in subset if c in df.columns]
    return df.drop_duplicates(subset=subset, keep="last").reset_index(drop=True)

def load_existing_team_data(season: int) -> pd.DataFrame:
    team_json = team_json_path(season)
    team_csv = team_csv_path(season)

    if team_json.exists():
        try:
            with open(team_json, "r", encoding="utf-8") as f:
                data = json.load(f)
            return align_team_schema(pd.DataFrame(data))
        except Exception:
            pass

    if team_csv.exists():
        try:
            return align_team_schema(pd.read_csv(team_csv))
        except Exception:
            pass

    return pd.DataFrame(columns=TEAM_OUTPUT_COLUMNS)


def load_existing_player_data(season: int) -> pd.DataFrame:
    player_json = player_json_path(season)
    player_csv = player_csv_path(season)

    if player_json.exists():
        try:
            with open(player_json, "r", encoding="utf-8") as f:
                data = json.load(f)
            return align_player_schema(pd.DataFrame(data))
        except Exception:
            pass

    if player_csv.exists():
        try:
            return align_player_schema(pd.read_csv(player_csv))
        except Exception:
            pass

    return pd.DataFrame(columns=PLAYER_OUTPUT_COLUMNS)


def align_team_schema(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=TEAM_OUTPUT_COLUMNS)

    for col in TEAM_OUTPUT_COLUMNS:
        if col not in df.columns:
            df[col] = None

    extra_cols = [c for c in df.columns if c not in TEAM_OUTPUT_COLUMNS]
    ordered_cols = TEAM_OUTPUT_COLUMNS + extra_cols
    return df[ordered_cols]


def align_player_schema(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=PLAYER_OUTPUT_COLUMNS)

    for col in PLAYER_OUTPUT_COLUMNS:
        if col not in df.columns:
            df[col] = None

    extra_cols = [c for c in df.columns if c not in PLAYER_OUTPUT_COLUMNS]
    ordered_cols = PLAYER_OUTPUT_COLUMNS + extra_cols
    return df[ordered_cols]


def write_season_outputs(season: int, team_df_all: pd.DataFrame, player_df_all: pd.DataFrame, write_csv: bool):
    team_df_all = align_team_schema(team_df_all)
    player_df_all = align_player_schema(player_df_all)

    if not team_df_all.empty:
        sort_cols = [c for c in ["season", "round_num", "home_team", "away_team"] if c in team_df_all.columns]
        if sort_cols:
            team_df_all = team_df_all.sort_values(sort_cols).reset_index(drop=True)

    if not player_df_all.empty:
        sort_cols = [c for c in ["season", "round_num", "home_team", "away_team", "team_side", "team", "number"] if c in player_df_all.columns]
        if sort_cols:
            player_df_all = player_df_all.sort_values(sort_cols).reset_index(drop=True)

    with open(team_json_path(season), "w", encoding="utf-8") as f:
        json.dump(team_df_all.to_dict("records"), f, ensure_ascii=False, indent=2)

    with open(player_json_path(season), "w", encoding="utf-8") as f:
        json.dump(player_df_all.to_dict("records"), f, ensure_ascii=False, indent=2)

    if write_csv:
        team_df_all.to_csv(team_csv_path(season), index=False)
        player_df_all.to_csv(player_csv_path(season), index=False)


# =========================================================
# ROUND / MATCH SCRAPING
# =========================================================
def get_round_game_urls(page, season, round_num):
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

def capture_team_stats_text(page, team_tab_wait_ms: int):
    click_named_tab(page, "Team Stats", wait_ms=team_tab_wait_ms)
    return get_body_text(page)


def capture_player_stats_texts(page, home_team: str, away_team: str, player_tab_wait_ms: int, away_toggle_wait_ms: int):
    click_named_tab(page, "Player Stats", wait_ms=player_tab_wait_ms)
    home_text = get_body_text(page)

    away_clicked = click_player_team_selector(
        page,
        away_team,
        team_to_section_labels(away_team),
        wait_ms=away_toggle_wait_ms,
    )
    away_text = get_body_text(page) if away_clicked else None

    return home_text, away_text, away_clicked


def scrape_match(page, url, season, round_num, round_slug, round_label, initial_page_wait_ms: int, team_tab_wait_ms: int, player_tab_wait_ms: int, away_toggle_wait_ms: int):
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(initial_page_wait_ms)
    accept_cookies(page)

    home_team, away_team = derive_teams_from_url(url)
    if not home_team or not away_team:
        raise ValueError(f"Could not derive teams from URL: {url}")

    team_text = capture_team_stats_text(page, team_tab_wait_ms=team_tab_wait_ms)
    home_player_text, away_player_text, away_clicked = capture_player_stats_texts(
        page,
        home_team,
        away_team,
        player_tab_wait_ms=player_tab_wait_ms,
        away_toggle_wait_ms=away_toggle_wait_ms,
    )

    home_score, away_score = extract_scores_from_page(page)

    team_row = {
        "season": season,
        "round_num": round_num,
        "round": round_label,
        "round_slug": round_slug,
        "url": url,
        "home_team": home_team,
        "away_team": away_team,
        "home_score": home_score,
        "away_score": away_score,
        "scrape_status": "ok",
    }
    team_row.update(extract_team_stats(team_text))

    game_meta = {
        "season": season,
        "round_num": round_num,
        "round": round_label,
        "round_slug": round_slug,
        "url": url,
        "home_team": home_team,
        "away_team": away_team,
    }

    player_rows = []
    player_rows.extend(
        extract_player_stats_from_single_team_text(home_player_text, game_meta, team_side="home")
    )

    if away_player_text:
        player_rows.extend(
            extract_player_stats_from_single_team_text(away_player_text, game_meta, team_side="away")
        )

    if player_rows:
        df = pd.DataFrame(player_rows)
        subset = ["season", "round_slug", "home_team", "away_team", "team", "team_side", "player", "number"]
        player_rows = df.drop_duplicates(subset=subset, keep="first").to_dict("records")

    return team_row, player_rows, away_clicked


def scrape_round(page, season: int, round_num: int, round_slug: str, round_label: str, args, force: bool = False):
    game_urls = get_round_game_urls(page, season, round_num)
    print(f"\nSeason {season} | {round_label}: found {len(game_urls)} game URLs")

    if not game_urls:
        return pd.DataFrame(), pd.DataFrame()

    team_rows = []
    player_rows = []

    for i, url in enumerate(game_urls, start=1):
        print(f"[Season {season} | {round_label} | {i}/{len(game_urls)}] Scraping {url}")
        try:
            team_row, players, away_clicked = scrape_match(
                page=page,
                url=url,
                season=season,
                round_num=round_num,
                round_slug=round_slug,
                round_label=round_label,
                initial_page_wait_ms=args.initial_page_wait_ms,
                team_tab_wait_ms=args.team_tab_wait_ms,
                player_tab_wait_ms=args.player_tab_wait_ms,
                away_toggle_wait_ms=args.away_toggle_wait_ms,
            )
            team_rows.append(team_row)
            player_rows.extend(players)
            print(f"   -> players={len(players)} | away_clicked={away_clicked}")

        except PlaywrightTimeoutError:
            print("   -> timeout")
            home_team, away_team = derive_teams_from_url(url)
            team_rows.append({
                "season": season,
                "round_num": round_num,
                "round": round_label,
                "round_slug": round_slug,
                "url": url,
                "home_team": home_team,
                "away_team": away_team,
                "scrape_status": "timeout",
            })

        except Exception as e:
            print(f"   -> error: {e}")
            home_team, away_team = derive_teams_from_url(url)
            team_rows.append({
                "season": season,
                "round_num": round_num,
                "round": round_label,
                "round_slug": round_slug,
                "url": url,
                "home_team": home_team,
                "away_team": away_team,
                "scrape_status": f"error: {e}",
            })

        time.sleep(args.request_sleep)

    team_df_round = align_team_schema(dedupe_team_df(pd.DataFrame(team_rows)))
    player_df_round = align_player_schema(dedupe_player_df(pd.DataFrame(player_rows)))

    # When force=True the user explicitly requested this round (--force-round),
    # so keep all games regardless of score — some may still be unplayed.
    # Without force, drop unplayed fixtures so they don't pollute the JSON and
    # so the empty-round counter can stop the scraper at the right round.
    if not force and not team_df_round.empty and "home_score" in team_df_round.columns:
        played_mask = team_df_round["home_score"].notna()
        if not played_mask.any():
            # Entire round is unplayed — return empty so the caller's empty-round
            # counter increments and the scraper stops cleanly.
            return pd.DataFrame(columns=team_df_round.columns), pd.DataFrame(columns=player_df_round.columns)
        team_df_round = team_df_round[played_mask].reset_index(drop=True)
        if not player_df_round.empty:
            played_urls = set(team_df_round["url"].dropna())
            url_col = next((c for c in ["game_url", "url"] if c in player_df_round.columns), None)
            if url_col:
                player_df_round = player_df_round[player_df_round[url_col].isin(played_urls)].reset_index(drop=True)

    return team_df_round, player_df_round


def scrape_single_season(page, season: int, args):
    existing_team_df = load_existing_team_data(season)
    existing_player_df = load_existing_player_data(season)

    missing_rounds = set(get_missing_rounds_for_season(season))

    # --force-round: add the specified rounds back into the scrape set
    # regardless of whether they already have saved data.
    force_rounds = set(args.force_round) if getattr(args, "force_round", None) else set()
    if force_rounds:
        missing_rounds |= force_rounds
        print(f"Season {season} force-round override: {sorted(force_rounds)}")

    if not missing_rounds:
        print(f"Season {season} already complete. Skipping.")
        return

    print(f"Season {season} missing/target rounds: {sorted(missing_rounds)}")

    all_team_dfs = []
    all_player_dfs = []

    # Load existing data. For force-round rounds, drop their old rows so the
    # fresh scrape replaces them cleanly rather than creating duplicates.
    if not existing_team_df.empty:
        if force_rounds and "round_num" in existing_team_df.columns:
            existing_team_df = existing_team_df[
                ~existing_team_df["round_num"].isin(force_rounds)
            ].reset_index(drop=True)
        all_team_dfs.append(existing_team_df)

    if not existing_player_df.empty:
        if force_rounds and "round_num" in existing_player_df.columns:
            existing_player_df = existing_player_df[
                ~existing_player_df["round_num"].isin(force_rounds)
            ].reset_index(drop=True)
        all_player_dfs.append(existing_player_df)

    consecutive_empty_rounds = 0

    for round_num, round_slug, round_label in get_round_configs():
        if round_num not in missing_rounds:
            continue

        team_df_round, player_df_round = scrape_round(
            page, season, round_num, round_slug, round_label, args,
            force=round_num in force_rounds,
        )

        if team_df_round.empty:
            consecutive_empty_rounds += 1
            print(
                f"Season {season} | {round_label}: no played games found "
                f"({consecutive_empty_rounds}/{args.empty_round_stop})"
            )

            if consecutive_empty_rounds >= args.empty_round_stop:
                print(
                    f"Stopping season {season} after "
                    f"{args.empty_round_stop} consecutive empty rounds."
                )
                break

            continue

        consecutive_empty_rounds = 0

        all_team_dfs.append(team_df_round)

        if not player_df_round.empty:
            all_player_dfs.append(player_df_round)

        team_df_all = align_team_schema(
            dedupe_team_df(pd.concat(all_team_dfs, ignore_index=True))
        )

        if all_player_dfs:
            player_df_all = align_player_schema(
                dedupe_player_df(pd.concat(all_player_dfs, ignore_index=True))
            )
        else:
            player_df_all = pd.DataFrame(columns=PLAYER_OUTPUT_COLUMNS)

        write_season_outputs(season, team_df_all, player_df_all, write_csv=args.write_csv)

        print(f"Season {season} | {round_label}: wrote season outputs.")
        print(f"   team rows this round: {len(team_df_round)}")
        print(f"   player rows this round: {len(player_df_round)}")
        print(f"   remaining rounds after write: {sorted(set(get_missing_rounds_for_season(season)))}")

        time.sleep(args.round_sleep)

def scrape_seasons(args):
    seasons = list(range(args.start_season, args.end_season + 1))
    headless = False if args.show_browser else args.headless

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            viewport={"width": 1440, "height": 2000},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        for season in seasons:
            if args.force_rescrape:
                print(f"\n{'=' * 60}")
                print(f"Force re-scraping season {season}")
                print(f"{'=' * 60}")
            else:
                missing_rounds = get_missing_rounds_for_season(season)

                if not missing_rounds:
                    print(f"Skipping season {season}: all 31 rounds already scraped.")
                    continue

                print(f"\n{'=' * 60}")
                print(f"Starting/resuming scrape for season {season}")
                print(f"Missing rounds: {missing_rounds}")
                print(f"{'=' * 60}")

            scrape_single_season(page, season, args)

            print(f"Finished scrape for season {season}")
            print(f"   Team JSON: {team_json_path(season)}")
            print(f"   Player JSON: {player_json_path(season)}")

            time.sleep(args.season_sleep)

        browser.close()


if __name__ == "__main__":
    args = parse_args()
    scrape_seasons(args)