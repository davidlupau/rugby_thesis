"""
Player-minutes scraping runner.

    python working_file_test.py            → quick test: 5-match sample
                                             (data/test_data/matches_list_sample_5.csv),
                                             writes data/processed/player_minutes_test.csv

    python working_file_test.py full       → full run: all matches in
                                             data/processed/matches_list.csv minus the
                                             ones already in dropped_matches_log.csv
                                             (~870), writes data/processed/player_minutes.csv
                                             with checkpointing + resume.
"""
import sys
import time

import pandas as pd

from src.utils import load_dataset
from src.collection.scrape_lnr_players import (
    scrape_player_minutes,
    filter_matches_for_minutes,
    MINUTES_INCOMPLETE_LOG,
)

pd.set_option("display.max_rows", None)
pd.set_option("display.width", 200)

MODE = sys.argv[1] if len(sys.argv) > 1 else "quick"


def run_quick() -> None:
    """5-match sample — fast iteration, unchanged behaviour."""
    df_matches = load_dataset("test_data", "matches_list_sample_5.csv")
    print(f"Test match(es): {df_matches['match_id'].tolist()}\n")

    df_minutes = scrape_player_minutes(
        df_matches,
        output_csv="player_minutes_test.csv",
        delay=2.0,
        resume=False,   # always re-scrape the sample for a clean quick test
    )

    print("\n" + "=" * 80)
    print(df_minutes.to_string(index=False))
    print("=" * 80)
    print(f"\nDone: {len(df_minutes)} rows "
          f"({df_minutes['team'].nunique()} teams) saved to "
          f"data/processed/player_minutes_test.csv")


def run_full() -> None:
    """All ~870 retained matches → data/processed/player_minutes.csv."""
    t0 = time.time()

    df_all = load_dataset("processed", "matches_list.csv")
    df_todo = filter_matches_for_minutes(df_all)   # drops dropped_matches_log.csv ids
    print(f"\nFull run: {len(df_all)} matches → {len(df_todo)} after "
          f"dropped_matches_log.csv filter\n")

    df_minutes = scrape_player_minutes(
        df_todo,
        output_csv="player_minutes.csv",
        incomplete_csv=MINUTES_INCOMPLETE_LOG,
        delay=2.0,
        resume=True,
        checkpoint_every=10,
    )

    elapsed = time.time() - t0

    # incomplete-log breakdown
    inc = load_dataset("processed", MINUTES_INCOMPLETE_LOG)
    if inc is not None and len(inc):
        known = int(inc["previously_known"].astype(bool).sum())
        new = len(inc) - known
    else:
        known = new = 0

    print("\n" + "=" * 80)
    print("FULL RUN SUMMARY")
    print("=" * 80)
    print(f"  matches attempted (post-filter):  {len(df_todo)}")
    print(f"  matches with >=1 row scraped:      {df_minutes['match_id'].nunique()}")
    print(f"  total player-minute rows written:  {len(df_minutes)}")
    print(f"  incomplete-log rows:              {known + new}  "
          f"(previously known: {known}, NEW: {new})")
    print(f"  elapsed:                          {elapsed / 60:.1f} min")
    print("\n  output:  data/processed/player_minutes.csv")
    print(f"  log:     data/processed/{MINUTES_INCOMPLETE_LOG}")


if __name__ == "__main__":
    #run_full()
    df = pd.read_csv("data/processed/player_minutes.csv")  # adjust path as needed
    print(df.shape)
    print("duplicate (match_id, player_id):", df.duplicated(subset=["match_id","player_id"]).sum())
    print("match_id count:", df["match_id"].nunique(), "— expect 870 minus any in incomplete_log")
    
    incomplete = pd.read_csv("data/processed/player_minutes_incomplete_log.csv")
    print(incomplete["previously_known"].value_counts())
