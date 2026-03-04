import pandas as pd
from src.utils import load_dataset, save_to_csv
from src.collection.scrape_lnr import scrape_lnr
from src.collection.scrape_lnr_players import scrape_player_registry
from src.collection.scrape_wikipedia import scrape_international_windows


def main():
    # -------------------------------------------------------------------------
    # 1. Load test match list
    # -------------------------------------------------------------------------
    # df_matches_list = load_dataset("test_data", "matches_list_sample.csv")

    # -------------------------------------------------------------------------
    # 2. Scrape regular season matches
    #    → produces: data/processed/regular_season_stats.csv
    #    → produces: data/processed/player_urls.csv  (one URL per player, deduplicated)
    # -------------------------------------------------------------------------
    #print("Scraping statistics for regular season matches...")
    #df_regular_season_stats = scrape_lnr(df_matches_list)

    #print(f"Regular season stats DataFrame: {len(df_regular_season_stats)} rows, "
    #      f"columns: {list(df_regular_season_stats.columns)}")

    # -------------------------------------------------------------------------
    # 3. Scrape playoff matches (commented out for test — uncomment for full run)
    # -------------------------------------------------------------------------
    # print("Scraping statistics for playoff matches...")
    # df_playoff_match_list = load_dataset("reference", "playoffs.csv")
    # df_playoff_stats = scrape_lnr(df_playoff_match_list, output_csv="playoff_stats.csv")

    # -------------------------------------------------------------------------
    # 4. Scrape individual player profiles with season statistics
    #    Uses match data to collect URLs and scrape profiles with season stats.
    #    → produces: data/processed/player_urls.csv         (URLs only)
    #    → produces: data/processed/players.csv         (name + nationality + season stats)
    # -------------------------------------------------------------------------
    # df_players_info = scrape_player_registry(df_matches_list)
    # print(f"Successfully scraped info for {len(df_players_info)} players")
    
    # Scrape international player call-ups from Wikipedia
    print("Scraping international player call-ups from Wikipedia...")
    df_international_window = load_dataset("reference", "international_windows.csv")
    df_international_players = scrape_international_windows(df_international_window)



if __name__ == "__main__":
    main()