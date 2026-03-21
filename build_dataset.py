import pandas as pd
from src.collection.scrape_matches_list import scrape_matches_list
from src.collection.scrape_lnr import scrape_lnr
from src.collection.scrape_lnr_players import scrape_player_registry
from src.collection.scrape_wikipedia import scrape_international_windows
from src.utils import load_dataset, save_to_csv

def main():
    
    # Load matches list
    df_matches_list = scrape_matches_list()

    # Scrape regular season matches — returns match stats + player-match records
    print("Scraping statistics for regular season matches...")
    df_regular_season_stats, df_player_match_stats = scrape_lnr(df_matches_list)

    # Scrape playoff matches — player records not needed for playoffs
    print("Scraping statistics for playoff matches...")
    df_playoff_match_list = load_dataset("reference", "playoffs.csv")
    df_playoff_stats, _ = scrape_lnr(df_playoff_match_list, output_csv="playoff_stats.csv")

    # Merge and save combined match stats
    print("Merging both datasets...")
    df_matches_stats_all = pd.concat(
        [df_regular_season_stats, df_playoff_stats], ignore_index=True
    )
    save_to_csv(df_matches_stats_all, "matches_stats_all.csv", "processed")
    print(f"Successfully created combined dataset with {len(df_matches_stats_all)} matches")

    # Scrape individual player info (name + nationality) for all unique players
    df_players_info = scrape_player_registry(df_player_match_stats)

    # Scrape international player call-ups from Wikipedia
    df_international_window = load_dataset("reference", "international_windows.csv")
    df_international_players = scrape_international_windows(df_international_window)

if __name__ == "__main__":
    main()