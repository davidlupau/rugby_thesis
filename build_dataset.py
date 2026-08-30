"""
Full pipeline for the Top 14 match dataset: scrape, retry incomplete
records, then clean and merge into the final analysis-ready dataset.

Function definitions live in src/ — this file just orchestrates them:
    src/collection/*.py                     — scraping
    src/collection/retry_scraping.py        — retrying incomplete records
    src/processing/clean_dataset.py         — dedup, merge, clean

Outputs (data/processed/):
    matches_list.csv            — raw fixture list, regular season + playoffs
    regular_season_stats.csv, playoff_stats.csv — raw per-match stats
    players.csv                 — deduped player registry
    player_callups.csv          — international call-ups from Wikipedia
    matches_stats_raw.csv       — regular+playoff merged, pre-cleaning (for reference)
    matches_stats_final.csv     — cleaned, analysis-ready match table
    dropped_matches_log.csv     — every row dropped during cleaning, with reason
    weather.csv                 — kickoff-time weather per match, from Open-Meteo
"""
from src.utils import load_dataset, save_to_csv
from src.collection.scrape_matches_list import scrape_matches_list
from src.collection.scrape_lnr import scrape_lnr
from src.collection.scrape_lnr_players import scrape_player_registry
from src.collection.scrape_wikipedia import scrape_international_windows
from src.collection.fetch_weather import fetch_weather_for_all_matches
from src.collection.retry_scraping import retry_incomplete_matches, retry_incomplete_players
from src.processing.clean_dataset import (
    dedup_players,
    build_merged_matches,
    drop_possession_columns,
    drop_bad_rows,
    sanity_checks,
)


def scrape_all():
    print("=" * 70)
    print("STAGE 1 — Scraping raw data")
    print("=" * 70)

    df_matches_list = scrape_matches_list()
    df_regular_season_list = df_matches_list[df_matches_list["is_playoff"] == 0].reset_index(drop=True)

    print("Scraping statistics for regular season matches...")
    scrape_lnr(df_regular_season_list)

    print("Scraping statistics for playoff matches...")
    df_playoff_match_list = load_dataset("reference", "playoffs.csv")
    scrape_lnr(df_playoff_match_list, output_csv="playoff_stats.csv")

    print("Scraping player registry...")
    scrape_player_registry(df_matches_list)

    # Scraping international player call-ups from Wikipedia
    # df_international_window = load_dataset("reference", "international_windows.csv")
    # scrape_international_windows(df_international_window)


def main():
    scrape_all()

    print("\n" + "=" * 70)
    print("STAGE 2 — Retrying incomplete records")
    print("=" * 70)
    retry_incomplete_matches()
    retry_incomplete_players()

    print("\n" + "=" * 70)
    print("STAGE 3 — Cleaning and finalizing")
    print("=" * 70)
    players_before, players_after = dedup_players()

    merged = build_merged_matches()
    save_to_csv(merged, "matches_stats_raw.csv", "processed")
    rows_before_drop = len(merged)

    merged = drop_possession_columns(merged)
    final_df, dropped_log = drop_bad_rows(merged)
    save_to_csv(final_df, "matches_stats_final.csv", "processed")

    sanity_checks(rows_before_drop, final_df, dropped_log, players_before, players_after)

    print("\n" + "=" * 70)
    print("STAGE 4 — Fetching weather data")
    print("=" * 70)
    fetch_weather_for_all_matches()


if __name__ == "__main__":
    main()
