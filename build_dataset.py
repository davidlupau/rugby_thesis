import pandas as pd
from src.collection.scrape_matches_list import scrape_matches_list
from src.utils import load_dataset, save_to_csv
from src.collection.scrape_lnr import scrape_lnr

def main():
    
    # Scrape the list of matches from LNR website
    df_matches_list = scrape_matches_list()
    
    # Scrape statistics of regular season matches
    print("Scraping statistics for regular season matches")
    df_regular_season_stats = scrape_lnr(df_matches_list)

    # Scapre statistics of playoff matches
    print("Scraping statistics for playoff matches")
    df_playoff_match_list = load_dataset("reference", "playoffs.csv")
    df_playoff_stats = scrape_lnr(df_playoff_match_list, output_csv="playoff_stats.csv")

    # Merge both DataFrames into a single comprehensive dataset
    print("Merging both datasets")
    df_matches_stats_all = pd.concat([df_regular_season_stats, df_playoff_stats], ignore_index=True)

    # Save the combined dataset
    save_to_csv(df_matches_stats_all, "matches_stats_all.csv", "processed")
    print(f"Successfully created combined dataset with {len(df_matches_stats_all)} matches")


if __name__ == "__main__":
    main()