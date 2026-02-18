import pandas as pd
from src.utils import load_dataset, save_to_csv
from src.collection.scrape_lnr import scrape_lnr

# Load and process regular season matches
df_matches_list = load_dataset("test_data", "matches_list_sample.csv")
df_regular_season_stats = scrape_lnr(df_matches_list)

# Load and process playoff matches
df_playoff_match_list = load_dataset("reference", "playoffs.csv")
df_playoff_stats = scrape_lnr(df_playoff_match_list, output_csv="playoff_stats.csv")

# Merge both DataFrames into a single comprehensive dataset
df_matches_stats_all = pd.concat([df_regular_season_stats, df_playoff_stats], ignore_index=True)

# Save the combined dataset
save_to_csv(df_matches_stats_all, "matches_stats_all.csv", "processed")

print(f"Successfully created combined dataset with {len(df_matches_stats_all)} matches")