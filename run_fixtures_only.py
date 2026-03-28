"""
run_fixtures_only.py

Scrapes ONLY fixtures (no stats) from RugbyLeagueProject
for all seasons INCLUDING FINALS and saves outputs.
"""

from pathlib import Path
import pandas as pd

from rlp_scraper import RLPFixturesAndStatsScraper


def save_fixtures_season_outputs(df: pd.DataFrame, out_dir: Path, season: int) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / f"rlp_nrl_fixtures_{season}.csv"
    json_path = out_dir / f"rlp_nrl_fixtures_{season}.json"

    df.to_csv(csv_path, index=False, encoding="utf-8")
    df.to_json(json_path, orient="records", indent=2, force_ascii=False)

    print(f"Saved CSV:  {csv_path}")
    print(f"Saved JSON: {json_path}")


def save_fixtures_combined_outputs(df_all: pd.DataFrame, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / "rlp_nrl_fixtures_all.csv"
    json_path = out_dir / "rlp_nrl_fixtures_all.json"

    df_all.to_csv(csv_path, index=False, encoding="utf-8")
    df_all.to_json(json_path, orient="records", indent=2, force_ascii=False)

    print(f"Saved combined CSV:  {csv_path}")
    print(f"Saved combined JSON: {json_path}")


if __name__ == "__main__":
    OUTPUT_ROOT = Path("../data/NRL")
    START_YEAR = 2015
    END_YEAR = 2026

    scraper = RLPFixturesAndStatsScraper(sleep_seconds=0.2)
    season_frames = []

    for season in range(START_YEAR, END_YEAR + 1):
        try:
            print(f"\n=== Scraping fixtures for {season} ===")
            
            # Scrape regular season + finals
            df = scraper.scrape_season_fixtures(season, include_finals=True)

            if df.empty:
                print(f"No data for {season}")
                continue

            # Map finals to numeric rounds for easier processing
            # Regular season is typically 26 rounds (can vary)
            # Map finals to Round 27, 28, 29, 30, 31
            finals_mapping = {
                'Qualifying Final': 27,
                'Elimination Final': 27,  # Week 1 of finals
                'Semi Final': 28,         # Week 2 of finals
                'Preliminary Final': 29,  # Week 3 of finals
                'Grand Final': 30         # Week 4 of finals
            }
            
            # Add a numeric_round column
            df['numeric_round'] = df['round'].copy()
            
            # For finals games, map to numeric
            for final_name, round_num in finals_mapping.items():
                mask = df['round'].str.contains(final_name, case=False, na=False)
                df.loc[mask, 'numeric_round'] = round_num
            
            # Convert numeric_round to int where possible
            df['numeric_round'] = pd.to_numeric(
                df['numeric_round'].astype(str).str.extract(r'(\d+)')[0], 
                errors='coerce'
            ).fillna(df['numeric_round'])

            save_fixtures_season_outputs(df, OUTPUT_ROOT / str(season), season)
            season_frames.append(df)
            
            print(f"  Regular season rounds: {df[df['numeric_round'] <= 26].shape[0]} games")
            print(f"  Finals games: {df[df['numeric_round'] > 26].shape[0]} games")

        except Exception as e:
            print(f"Error scraping {season}: {e}")

    if season_frames:
        df_all = pd.concat(season_frames, ignore_index=True)
        save_fixtures_combined_outputs(df_all, OUTPUT_ROOT)

        print("\nCombined summary:")
        print(df_all.groupby("season").size())
        print("\nFinals games by season:")
        print(df_all[df_all['numeric_round'] > 26].groupby("season").size())

    print("\nDone.")