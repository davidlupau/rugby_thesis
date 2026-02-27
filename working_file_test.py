import pandas as pd
from src.utils import load_dataset, save_to_csv
from src.collection.scrape_lnr import scrape_lnr
from src.collection.scrape_lnr_players import scrape_player_registry

def main():
    # Load and process regular season matches
    df_matches_list = load_dataset("test_data", "matches_list_sample.csv")
    
    scrape_player_registry(df_matches_list)
    
    # Scrape statistics for playoff matches
    print("Scraping statistics for playoff matches")
    df_playoff_match_list = load_dataset("reference", "playoffs.csv")
    df_playoff_stats = scrape_lnr(df_playoff_match_list, output_csv="playoff_stats.csv")
    
    # Merge and save the combined dataset
    print("Merging both datasets")
    df_matches_stats_all = pd.concat([df_regular_season_stats, df_playoff_stats], ignore_index=True)
    save_to_csv(df_matches_stats_all, "matches_stats_all.csv", "processed")
    print(f"Successfully created combined dataset with {len(df_matches_stats_all)} matches")
      
if __name__ == "__main__":
    main()