import sqlite3
from pathlib import Path

import pandas as pd

# =========================================================
# CONFIG
# =========================================================
SEASON = 2024

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "nrl_outputs"
TEAM_CSV = OUTPUT_DIR / f"nrl_{SEASON}_team_gamelogs.csv"
PLAYER_CSV = OUTPUT_DIR / f"nrl_{SEASON}_player_gamelogs.csv"
DB_PATH = OUTPUT_DIR / "nrl_stats.db"


def ensure_output_dir():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def load_csv_safe(path: Path) -> pd.DataFrame:
    if not path.exists():
        print(f"Missing file: {path}")
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception as e:
        print(f"Failed to read {path}: {e}")
        return pd.DataFrame()


def dedupe_team_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    subset = ["season", "round", "home_team", "away_team", "url"]
    subset = [c for c in subset if c in df.columns]
    return df.drop_duplicates(subset=subset, keep="last").reset_index(drop=True)


def dedupe_player_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    subset = ["season", "round", "home_team", "away_team", "team_side", "team", "player", "number"]
    subset = [c for c in subset if c in df.columns]
    return df.drop_duplicates(subset=subset, keep="last").reset_index(drop=True)


def create_indexes(conn: sqlite3.Connection):
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_team_gamelogs_season_round
        ON team_gamelogs (season, round)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_team_gamelogs_matchup
        ON team_gamelogs (season, home_team, away_team)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_player_gamelogs_season_round
        ON player_gamelogs (season, round)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_player_gamelogs_player
        ON player_gamelogs (player)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_player_gamelogs_match
        ON player_gamelogs (season, home_team, away_team, team_side)
    """)
    conn.commit()


def build_database(team_df: pd.DataFrame, player_df: pd.DataFrame):
    conn = sqlite3.connect(DB_PATH)

    if not team_df.empty:
        team_df.to_sql("team_gamelogs", conn, if_exists="replace", index=False)
        print(f"Loaded team_gamelogs: {len(team_df)} rows")
    else:
        print("team_gamelogs not loaded: empty dataframe")

    if not player_df.empty:
        player_df.to_sql("player_gamelogs", conn, if_exists="replace", index=False)
        print(f"Loaded player_gamelogs: {len(player_df)} rows")
    else:
        print("player_gamelogs not loaded: empty dataframe")

    create_indexes(conn)

    # Optional summary view
    conn.execute("DROP VIEW IF EXISTS v_player_try_summary")
    conn.execute("""
        CREATE VIEW v_player_try_summary AS
        SELECT
            season,
            player,
            team,
            COUNT(*) AS games_played,
            SUM(COALESCE(tries, 0)) AS total_tries,
            AVG(COALESCE(tries, 0)) AS avg_tries
        FROM player_gamelogs
        GROUP BY season, player, team
    """)
    conn.commit()
    conn.close()


def main():
    ensure_output_dir()

    team_df = load_csv_safe(TEAM_CSV)
    player_df = load_csv_safe(PLAYER_CSV)

    team_df = dedupe_team_df(team_df)
    player_df = dedupe_player_df(player_df)

    build_database(team_df, player_df)

    print(f"\nDatabase created/updated: {DB_PATH}")


if __name__ == "__main__":
    main()