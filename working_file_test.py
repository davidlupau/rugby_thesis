import pandas as pd
from src.utils import load_dataset, save_to_csv
from src.collection.scrape_lnr import scrape_lnr
from src.collection.scrape_lnr_players import scrape_player_registry

# Load and process regular season matches
df_matches_list = load_dataset("test_data", "matches_list_sample.csv")

scrape_player_registry(df_matches_list)