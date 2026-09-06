"""
Full pipeline for the Top 14 match dataset: scrape, retry incomplete
records, then clean and merge into the final analysis-ready dataset.

Function definitions live in src/ — this file just orchestrates them:
    src/collection/*.py                     — scraping
    src/collection/retry_scraping.py        — retrying incomplete records
    src/processing/clean_dataset.py         — dedup, merge, clean
    src/processing/build_international_calendar.py — international-window/round flags
    src/processing/build_callup_name_bridge.py      — call-up name -> player_id
    src/processing/apply_callup_review_decisions.py — reapplies human-reviewed bridge matches
    src/processing/calculate_players_away.py        — absence coefficient

Outputs (data/processed/):
    matches_list.csv            — raw fixture list, regular season + playoffs
    regular_season_stats.csv, playoff_stats.csv — raw per-match stats
    players.csv                 — deduped player registry
    player_callups.csv          — international call-ups from Wikipedia
    matches_stats_raw.csv       — regular+playoff merged, pre-cleaning (for reference)
    matches_stats_final.csv     — cleaned, analysis-ready match table
    dropped_matches_log.csv     — every row dropped during cleaning, with reason
    weather.csv                 — kickoff-time weather per match, from Open-Meteo
    international_calendar.csv  — flagged Top 14 rounds per international competition
    callup_name_bridge.csv      — call-up name -> player_id match
    player_minutes.csv          — match-by-match player participation
    players_away.csv            — per-match home/away absence coefficient

NOTE -- callup_name_bridge.csv has hand-curated rows that build_callup_name_bridge()
alone does NOT reproduce on a fresh rebuild (see that module's own
docstring). STAGE 5 restores both automatically, in either order:
    - "manual_review" tier (53 rows) via apply_callup_review_decisions(),
      reading callup_review_queue.csv
    - "manual_entry_profile_removed" tier -- Timani (11434) and Takulua (86)
      -- via apply_manual_bridge_entries(), hardcoded in that function so it
      survives even if callup_review_queue.csv itself is wiped
"""
from src.utils import load_dataset, save_to_csv
from src.collection.scrape_matches_list import scrape_matches_list
from src.collection.scrape_lnr import scrape_lnr
from src.collection.scrape_lnr_players import (
    scrape_player_registry,
    filter_matches_for_minutes,
    scrape_player_minutes,
)
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
from src.processing.build_international_calendar import build_international_calendar
from src.processing.build_callup_name_bridge import (
    build_callup_name_bridge,
    apply_manual_bridge_entries,
)
from src.processing.apply_callup_review_decisions import apply_callup_review_decisions
from src.processing.calculate_players_away import calculate_players_away


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

    print("\n" + "=" * 70)
    print("STAGE 5 — International call-up data")
    print("=" * 70)
    df_international_windows = load_dataset("reference", "international_windows.csv")
    scrape_international_windows(df_international_windows)

    build_international_calendar()
    build_callup_name_bridge()

    # Neither of the next two calls can undo the other -- each only ever
    # touches its own disjoint set of player_name rows -- so their order
    # doesn't matter. Together they restore everything build_callup_name_bridge()
    # cannot reproduce on its own:
    #   - the two hardcoded "manual_entry_profile_removed" rows (Timani
    #     11434, Takulua 86), whose LNR profile pages are gone;
    #   - the hand-reviewed "manual_review" tier from callup_review_queue.csv.
    apply_manual_bridge_entries()
    apply_callup_review_decisions()

    print("\n" + "=" * 70)
    print("STAGE 6 — Player minutes")
    print("=" * 70)
    df_matches_list = load_dataset("processed", "matches_list.csv")
    df_matches_for_minutes = filter_matches_for_minutes(df_matches_list)
    scrape_player_minutes(df_matches_for_minutes)

    print("\n" + "=" * 70)
    print("STAGE 7 — Absence coefficient")
    print("=" * 70)
    calculate_players_away()

    # Next stage to slot in here: European congestion / travel / form
    # features -- none of those are built yet.


if __name__ == "__main__":
    main()
