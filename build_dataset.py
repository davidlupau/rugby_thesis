import pandas as pd
from src.scrape_matches_list import scrape_matches_list
from src.collection.scrape_lnr import scrape_lnr
from src.utils import load_dataset, save_to_csv

def main():
    # Load matches data
    df_matches_list = scrape_matches_list()
    
    # Scrape statistics for regular season matches
    print("Scraping statistics for regular season matches")
    df_regular_season_stats = scrape_lnr(df_matches_list)

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