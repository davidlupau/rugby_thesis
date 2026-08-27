import pandas as pd
from src.utils import load_dataset, save_to_csv
from src.collection.scrape_lnr import scrape_lnr
from src.collection.scrape_lnr_players import scrape_player_registry
from src.collection.scrape_wikipedia import scrape_international_windows
from src.collection.scrape_matches_list import scrape_matches_list


def main():
    # -------------------------------------------------------------------------
    # 1. Scrape the full match list (all rounds, all seasons in SEASONS)
    #    → produces: data/processed/matches_list.csv
    # -------------------------------------------------------------------------
    #print("Scraping match list for all seasons...")
    #df_matches_list = scrape_matches_list()
    #df_matches_list = df_matches_list[df_matches_list['is_playoff'] == 0].reset_index(drop=True)

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
    #df_players_info = scrape_player_registry(df_matches_list)
    #print(f"Successfully scraped info for {len(df_players_info)} players")
    
    # -------------------------------------------------------------------------
    # 1. Load playoff match list
    # -------------------------------------------------------------------------
    df_playoff_match_list = load_dataset("reference", "playoffs.csv")

    # -------------------------------------------------------------------------
    # 2. Scrape playoff matches
    #    → produces: data/processed/playoff_stats.csv
    #    → produces: data/processed/player_urls.csv  (one URL per player, deduplicated)
    # -------------------------------------------------------------------------
    print("Scraping statistics for playoff matches...")
    df_playoff_stats = scrape_lnr(df_playoff_match_list, output_csv="playoff_stats.csv")

    print(f"Playoff stats DataFrame: {len(df_playoff_stats)} rows, "
          f"columns: {list(df_playoff_stats.columns)}")
    


if __name__ == "__main__":
    main()