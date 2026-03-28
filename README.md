# NRL Data Scraper

Scrapes team stats and player game logs from [nrl.com](https://www.nrl.com), plus named team lists for upcoming rounds. Data is stored as JSON and optionally converted to CSV.

---

## Prerequisites

Install dependencies (requires [Playwright](https://playwright.dev/python/)):

```bash
pip install playwright pandas
playwright install chromium
```

---

## Workflow Overview

```
1. scrape_nrl_seasons.py   →   nrl_outputs/nrl_{season}_team_gamelogs.json
                           →   nrl_outputs/nrl_{season}_player_gamelogs.json

2. get_future_teams.py     →   nrl_outputs/nrl_{season}_round_{N}_team_lists.json  (upcoming rounds only)

3. convert_jsons_to_csvs.py →  nrl_outputs/nrl_{season}_team_gamelogs.csv
                            →  nrl_outputs/nrl_{season}_player_gamelogs.csv
                            →  nrl_outputs/nrl_all_seasons_team_gamelogs.csv
                            →  nrl_outputs/nrl_all_seasons_player_gamelogs.csv

4. clean_games_new.py      →   cleaned/transformed DataFrames ready for analysis
```

---

## Use Cases

### 1. Scrape a Single Season (Team + Player Data)

To scrape one season — for example, only the 2026 season — set both `--start-season` and `--end-season` to the same year:

```bash
python scrape_nrl_seasons.py --start-season 2026 --end-season 2026
```

The scraper **automatically detects which rounds are already saved** and only fetches missing ones, so it is safe to re-run at any time to pick up new rounds.

To also write CSV files alongside the JSON outputs, add `--write-csv`:

```bash
python scrape_nrl_seasons.py --start-season 2026 --end-season 2026 --write-csv
```

To see the browser while scraping (useful for debugging):

```bash
python scrape_nrl_seasons.py --start-season 2026 --end-season 2026 --show-browser
```

#### What gets saved per season

| File | Contents |
|---|---|
| `nrl_outputs/nrl_2026_team_gamelogs.json` | One row per team per game (both home and away stats) |
| `nrl_outputs/nrl_2026_player_gamelogs.json` | One row per player per game (full stat line) |

---

### 2. Scrape a Range of Seasons

To scrape multiple seasons in one run (e.g., 2020 through 2026):

```bash
python scrape_nrl_seasons.py --start-season 2020 --end-season 2026
```

Seasons that are **already fully scraped** (all 31 rounds present) are skipped automatically. To force a full re-scrape of every season in the range:

```bash
python scrape_nrl_seasons.py --start-season 2020 --end-season 2026 --force-rescrape
```

To scrape the full historical dataset (2015 onwards), use the defaults:

```bash
python scrape_nrl_seasons.py
```

#### Key CLI options

| Flag | Default | Description |
|---|---|---|
| `--start-season` | `2015` | First season to scrape |
| `--end-season` | `2026` | Last season to scrape |
| `--write-csv` | off | Also write per-season CSVs |
| `--force-rescrape` | off | Re-scrape even if data already exists |
| `--force-round` | off | Re-scrape specific round(s) even if already saved |
| `--show-browser` | off | Run with a visible browser window |
| `--empty-round-stop` | `2` | Stop a season after N consecutive empty rounds |

---

### 3. Re-scrape the Current Round (Partial Round Updates)

Once a round is saved to the JSON, the scraper considers it complete and will not re-visit it on subsequent runs. If you ran the scraper mid-week and only some of the round's games had been played, use `--force-round` to re-scrape that round and pick up the remaining results:

```bash
# Re-scrape round 4 only
python scrape_nrl_seasons.py --start-season 2026 --end-season 2026 --force-round 4
```

You can also target multiple rounds at once:

```bash
python scrape_nrl_seasons.py --start-season 2026 --end-season 2026 --force-round 3 4
```

`--force-round` strips the old rows for those rounds from the existing JSON, re-scrapes them fresh, then merges the result back in. All other saved rounds are left untouched.

> **Note:** `--force-round` and `--force-rescrape` are different. `--force-round` targets specific rounds only; `--force-rescrape` re-scrapes the entire season from scratch.

---

### 3. Get Named Team Lists for an Upcoming Round

`get_future_teams.py` scrapes the **named squads** (players, jersey numbers, positions) announced ahead of a round — before match stats are available. This is useful for building pre-game prediction features.

**Auto-detect the next upcoming round:**

```bash
python get_future_teams.py
```

**Target a specific season and round:**

```bash
python get_future_teams.py --season 2026 --round-num 5
```

#### What gets saved

| File | Contents |
|---|---|
| `nrl_outputs/nrl_2026_round_5_team_lists.json` | Named squad rows (player, number, position) |
| `nrl_outputs/nrl_2026_round_5_team_lists.csv` | Same data as CSV |

#### Key CLI options

| Flag | Default | Description |
|---|---|---|
| `--season` | auto-detect | Season to target |
| `--round-num` | auto-detect | Round number to target |
| `--show-browser` | off | Run with a visible browser window |

---

## Convert JSON Files to CSV

After scraping, run `convert_jsons_to_csvs.py` to convert all JSON files in `nrl_outputs/` into clean, deduplicated CSVs:

```bash
python convert_jsons_to_csvs.py
```

This will:
- Write a **per-season CSV** for every JSON file found (e.g., `nrl_2026_team_gamelogs.csv`)
- Write two **combined all-seasons CSVs**:
  - `nrl_outputs/nrl_all_seasons_team_gamelogs.csv`
  - `nrl_outputs/nrl_all_seasons_player_gamelogs.csv`

To skip writing per-season CSVs and only produce the combined files, set `WRITE_PER_SEASON_CSVS = False` at the top of the script.

---

## Clean and Transform the Data

`clean_games_new.py` loads the combined CSVs and applies transformations ready for modelling or analysis:

```bash
python clean_games_new.py
```

Key transformations applied:
- Sorts by `season` and `round_num`
- Merges player game logs with future team lists
- Strips `Coach` rows from player data
- Converts `mins_played`, `stint_one`, `stint_two` from `mm:ss` to decimal minutes
- Converts `time_in_possession` from `mm:ss` to total seconds
- Creates a `game_id` column (`{home_3_letters}{away_3_letters}{season}{round_num}`)
- Saves cleaned output to `nrl_outputs/nrl_tryscorers.csv`

---

## Output File Reference

| File | Script | Description |
|---|---|---|
| `nrl_outputs/nrl_{season}_team_gamelogs.json` | `scrape_nrl_seasons.py` | Raw team stats per game, per season |
| `nrl_outputs/nrl_{season}_player_gamelogs.json` | `scrape_nrl_seasons.py` | Raw player stats per game, per season |
| `nrl_outputs/nrl_{season}_round_{N}_team_lists.json` | `get_future_teams.py` | Named squads for an upcoming round |
| `nrl_outputs/nrl_{season}_team_gamelogs.csv` | `convert_jsons_to_csvs.py` | Per-season team stats CSV |
| `nrl_outputs/nrl_{season}_player_gamelogs.csv` | `convert_jsons_to_csvs.py` | Per-season player stats CSV |
| `nrl_outputs/nrl_all_seasons_team_gamelogs.csv` | `convert_jsons_to_csvs.py` | All seasons combined team stats |
| `nrl_outputs/nrl_all_seasons_player_gamelogs.csv` | `convert_jsons_to_csvs.py` | All seasons combined player stats |
| `nrl_outputs/nrl_tryscorers.csv` | `clean_games_new.py` | Cleaned and transformed player data |

---

## Finals Rounds

Finals rounds are mapped to the following round numbers:

| Round Number | Label |
|---|---|
| 28 | Finals Week 1 |
| 29 | Finals Week 2 |
| 30 | Finals Week 3 |
| 31 | Grand Final |
