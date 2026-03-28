import json
import re
from pathlib import Path

import pandas as pd

# =========================================================
# CONFIG
# =========================================================
BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "nrl_outputs"
OUTPUT_DIR = BASE_DIR / "nrl_outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TEAM_JSON_PATTERN = "nrl_*_team_gamelogs.json"
PLAYER_JSON_PATTERN = "nrl_*_player_gamelogs.json"

COMBINED_TEAM_CSV = OUTPUT_DIR / "nrl_all_seasons_team_gamelogs.csv"
COMBINED_PLAYER_CSV = OUTPUT_DIR / "nrl_all_seasons_player_gamelogs.csv"

# Optional cleaned per-season CSVs will be written beside the JSONs
WRITE_PER_SEASON_CSVS = True


# =========================================================
# HELPERS
# =========================================================
def extract_season_from_filename(path: Path):
    match = re.search(r"nrl_(\d{4})_", path.name)
    return int(match.group(1)) if match else None


def load_json_records(path: Path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except Exception as e:
        print(f"Failed to load {path.name}: {e}")
        return []


def safe_numeric_round(df: pd.DataFrame) -> pd.DataFrame:
    if "round_num" in df.columns:
        df["round_num"] = pd.to_numeric(df["round_num"], errors="coerce")
    if "season" in df.columns:
        df["season"] = pd.to_numeric(df["season"], errors="coerce")
    return df


def dedupe_team_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    subset = [c for c in ["season", "round_num", "round_slug", "home_team", "away_team", "url"] if c in df.columns]
    if subset:
        df = df.drop_duplicates(subset=subset, keep="last")
    return df.reset_index(drop=True)


def dedupe_player_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    subset = [c for c in ["season", "round_num", "round_slug", "home_team", "away_team", "team_side", "team", "player", "number"] if c in df.columns]
    if subset:
        df = df.drop_duplicates(subset=subset, keep="last")
    return df.reset_index(drop=True)


def sort_team_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    sort_cols = [c for c in ["season", "round_num", "home_team", "away_team"] if c in df.columns]
    if sort_cols:
        df = df.sort_values(sort_cols).reset_index(drop=True)
    return df


def sort_player_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    sort_cols = [c for c in ["season", "round_num", "home_team", "away_team", "team_side", "team", "number", "player"] if c in df.columns]
    if sort_cols:
        df = df.sort_values(sort_cols).reset_index(drop=True)
    return df


def reorder_columns(df: pd.DataFrame, preferred_first_cols: list[str]) -> pd.DataFrame:
    if df.empty:
        return df
    first = [c for c in preferred_first_cols if c in df.columns]
    remaining = [c for c in df.columns if c not in first]
    return df[first + remaining]


def write_per_season_csv(df: pd.DataFrame, season: int, kind: str):
    out_path = OUTPUT_DIR / f"nrl_{season}_{kind}.csv"
    df.to_csv(out_path, index=False)
    print(f"Wrote {out_path.name} ({len(df)} rows)")


# =========================================================
# CONVERTERS
# =========================================================
def process_team_jsons():
    team_files = sorted(INPUT_DIR.glob(TEAM_JSON_PATTERN))
    all_dfs = []

    if not team_files:
        print("No team JSON files found.")
        return pd.DataFrame()

    for path in team_files:
        season = extract_season_from_filename(path)
        records = load_json_records(path)
        df = pd.DataFrame(records)

        if df.empty:
            print(f"Skipping empty team JSON: {path.name}")
            continue

        if season is not None and "season" not in df.columns:
            df["season"] = season

        df = safe_numeric_round(df)
        df = dedupe_team_df(df)
        df = sort_team_df(df)

        df = reorder_columns(df, [
            "season", "round_num", "round", "round_slug", "url",
            "home_team", "away_team", "home_score", "away_score", "scrape_status"
        ])

        if WRITE_PER_SEASON_CSVS and season is not None:
            write_per_season_csv(df, season, "team_gamelogs")

        all_dfs.append(df)

    if not all_dfs:
        return pd.DataFrame()

    combined = pd.concat(all_dfs, ignore_index=True, sort=False)
    combined = safe_numeric_round(combined)
    combined = dedupe_team_df(combined)
    combined = sort_team_df(combined)
    combined = reorder_columns(combined, [
        "season", "round_num", "round", "round_slug", "url",
        "home_team", "away_team", "home_score", "away_score", "scrape_status"
    ])
    return combined


def process_player_jsons():
    player_files = sorted(INPUT_DIR.glob(PLAYER_JSON_PATTERN))
    all_dfs = []

    if not player_files:
        print("No player JSON files found.")
        return pd.DataFrame()

    for path in player_files:
        season = extract_season_from_filename(path)
        records = load_json_records(path)
        df = pd.DataFrame(records)

        if df.empty:
            print(f"Skipping empty player JSON: {path.name}")
            continue

        if season is not None and "season" not in df.columns:
            df["season"] = season

        df = safe_numeric_round(df)
        df = dedupe_player_df(df)
        df = sort_player_df(df)

        df = reorder_columns(df, [
            "season", "round_num", "round", "round_slug", "game_url",
            "home_team", "away_team", "team_side", "team",
            "player", "number", "position", "mins_played"
        ])

        if WRITE_PER_SEASON_CSVS and season is not None:
            write_per_season_csv(df, season, "player_gamelogs")

        all_dfs.append(df)

    if not all_dfs:
        return pd.DataFrame()

    combined = pd.concat(all_dfs, ignore_index=True, sort=False)
    combined = safe_numeric_round(combined)
    combined = dedupe_player_df(combined)
    combined = sort_player_df(combined)
    combined = reorder_columns(combined, [
        "season", "round_num", "round", "round_slug", "game_url",
        "home_team", "away_team", "team_side", "team",
        "player", "number", "position", "mins_played"
    ])
    return combined


# =========================================================
# MAIN
# =========================================================
def main():
    print("Converting team JSON files...")
    combined_team_df = process_team_jsons()

    print("\nConverting player JSON files...")
    combined_player_df = process_player_jsons()

    if not combined_team_df.empty:
        combined_team_df.to_csv(COMBINED_TEAM_CSV, index=False)
        print(f"\nWrote combined team CSV: {COMBINED_TEAM_CSV} ({len(combined_team_df)} rows)")
    else:
        print("\nNo combined team CSV written.")

    if not combined_player_df.empty:
        combined_player_df.to_csv(COMBINED_PLAYER_CSV, index=False)
        print(f"Wrote combined player CSV: {COMBINED_PLAYER_CSV} ({len(combined_player_df)} rows)")
    else:
        print("No combined player CSV written.")

    print("\nDone.")


if __name__ == "__main__":
    main()