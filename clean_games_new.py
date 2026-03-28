# %%

import pandas as pd
import numpy as np
import os
#show all columns
pd.set_option('display.max_columns', None)

path = r'C:/Users/jbull/OneDrive/Documents/Python Projects/NRL/python files/nrl_outputs/'
df = pd.read_csv(os.path.join(path, "nrl_all_seasons_team_gamelogs.csv"))
players_df = pd.read_csv(os.path.join(path, "nrl_all_seasons_player_gamelogs.csv"))
future_gamelists_df = pd.read_csv(os.path.join(path, "nrl_2026_round_4_team_lists.csv"))

#sort by season, round_num
df = df.sort_values(by=['season', 'round_num'], ascending=[True, True])
df

# %%
players_df

# %%
future_gamelists_df

# %%
#concat future_gamelists_df with players_df
combined_df = pd.concat([players_df, future_gamelists_df], ignore_index=True)
#sort by season, round_num
combined_df = combined_df.sort_values(by=['season', 'round_num'], ascending=[True, True])
#remove rows where position is "Coach"
combined_df = combined_df[combined_df['position'] != 'Coach']
#convert number to int
combined_df['number'] = combined_df['number'].astype(int)
#drop round, game_url from combined_df
combined_df = combined_df.drop(columns=['round', 'game_url', 'round_slug'])
#convert mins_played, stint_one and stint_two to numeric as it is mm:ss
def convert_time_to_minutes(time_str):
    if pd.isna(time_str):
        return 0
    try:
        minutes, seconds = map(int, time_str.split(':'))
        return minutes + seconds / 60
    except ValueError:
        return 0
combined_df['mins_played'] = combined_df['mins_played'].apply(convert_time_to_minutes)
combined_df['stint_one'] = combined_df['stint_one'].apply(convert_time_to_minutes)
combined_df['stint_two'] = combined_df['stint_two'].apply(convert_time_to_minutes)
#save combined_df to csv
combined_df.to_csv(os.path.join(path, "nrl_tryscorers.csv"), index=False)
combined_df

# %%
#create game_id which is first 3 letters of home team + first 3 letters of away team + season + round_num
df['game_id'] = df['home_team'].str[:3] + df['away_team'].str[:3] + df['season'].astype(str) + df['round_num'].astype(str)
df

# %%
#get a list of all columns in df
cols = df.columns.tolist()
print(cols)

# %%
#get unique values for home_team, sort by alphabetical order
teams = df['home_team'].unique().tolist()
teams.sort()
teams

# %%
#convert home_time_in_possession from mm:ss to seconds
def time_to_seconds(time_str):
    if pd.isna(time_str):
        return np.nan
    try:
        minutes, seconds = map(int, time_str.split(':'))
        return minutes * 60 + seconds
    except ValueError:
        return np.nan
    
df['home_time_in_possession'] = df['home_time_in_possession'].apply(time_to_seconds)
df['away_time_in_possession'] = df['away_time_in_possession'].apply(time_to_seconds)

# %%
#drop cols
cols_to_drop = ['round', 'round_slug', 'url', 'scrape_status', 
                'home_completion_rate', 'away_completion_rate', 'home_completion_rate_made_attempted', 'away_completion_rate_made_attempted', 'home_time_in_possession', 'away_time_in_possession']
df.drop(columns=cols_to_drop, inplace=True)
df

# %%
#see if there is any nan values in home_team or away_team
print(df[df['home_team'].isna()])

# %%
import pandas as pd
import numpy as np

# 1. Ensure date and round are the correct types
df['round_num'] = pd.to_numeric(df['round_num'], errors="coerce")

# 2. Create a "Long" view to track every team's round history independently
home_view = df[['season', 'round_num', 'home_team']].rename(columns={'home_team': 'team'})
away_view = df[['season', 'round_num', 'away_team']].rename(columns={'away_team': 'team'})
team_history = pd.concat([home_view, away_view]).sort_values(['team', 'season', 'round_num'])

# 3. Calculate the previous round each team played
team_history['prev_round_played'] = team_history.groupby(['season', 'team'])['round_num'].shift(1)

# 4. If the gap between current round and prev round > 1, they had a Bye
# (We fillna with 'round - 1' so Round 1 doesn't count as a Bye)
team_history['round_gap'] = team_history['round_num'] - team_history['prev_round_played'].fillna(team_history['round_num'] - 1)
team_history['off_bye'] = (team_history['round_gap'] > 1).astype(int)

# 5. Map the results back to the original dataframe for Home and Away
home_bye_map = team_history.set_index(['team', 'season', 'round_num'])['off_bye']

df['home_team_off_bye'] = df.apply(lambda x: home_bye_map.get((x['home_team'], x['season'], x['round_num']), 0), axis=1)
df['away_team_off_bye'] = df.apply(lambda x: home_bye_map.get((x['away_team'], x['season'], x['round_num']), 0), axis=1)

# 6. Optional: Create a 'Rest Advantage' feature
df['bye_advantage'] = df['home_team_off_bye'] - df['away_team_off_bye']

# %%
#save to csv
output_path = r"C:/Users/jbull/OneDrive/Documents/Python Projects/NRL/python files/nrl_outputs/"
df.to_csv(os.path.join(output_path, "all_games_cleaned.csv"), index=False)


