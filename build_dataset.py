"""
Full pipeline for the Top 14 match dataset: scrape, retry incomplete
records, then clean and merge into the final analysis-ready dataset.

STAGE 1 — SCRAPE
    Match list (all seasons/rounds + playoffs), regular season + playoff
    match stats, player registry, international call-ups from Wikipedia.

STAGE 2 — RETRY INCOMPLETE RECORDS
    Matches: skips anything confirmed_no_data (verified against the live
    site — see src/constants.py::is_confirmed_dead), retries everything
    else, merges successful retries back into the main stats files.
    Players: retries player profile URLs missing from players.csv, tracking
    fail_count per player across runs; anything failing 3+ times is flagged
    manual_review_needed instead of a generic timeout.

STAGE 3 — CLEAN + FINALIZE
    Dedups players.csv on canonical player_id (LNR serves the same player
    from multiple domains). Merges regular season + playoff stats into one
    table, restricted to the 5 target seasons. Drops the unreliable general
    home/away_possession columns. Drops rows with no real data (scraper
    timeout or LNR published no stats), logging every drop with a reason.
    Prints sanity checks at the end.

Outputs (data/processed/):
    matches_list.csv            — raw fixture list, regular season + playoffs
    regular_season_stats.csv, playoff_stats.csv — raw per-match stats
    players.csv                 — deduped player registry
    player_callups.csv          — international call-ups from Wikipedia
    matches_stats_raw.csv       — regular+playoff merged, pre-cleaning (for reference)
    matches_stats_final.csv     — cleaned, analysis-ready match table
    dropped_matches_log.csv     — every row dropped during cleaning, with reason
"""
import pandas as pd

from src.utils import load_dataset, save_to_csv, extract_player_id
from src.collection.scrape_matches_list import scrape_matches_list
from src.collection.scrape_lnr import scrape_lnr
from src.collection.scrape_lnr_players import scrape_player_registry, phase2_scrape_profiles
from src.collection.scrape_wikipedia import scrape_international_windows
from src.constants import SEASONS as TARGET_SEASONS, is_confirmed_dead

# Known failure history that predates the fail_count tracking in
# phase2_scrape_profiles — used only to seed players_incomplete.csv the
# first time it's created, so the manual-review threshold is correct.
KNOWN_PRIOR_PLAYER_FAILURES = {"2019": 2}  # alexandre-perez: failed twice already


# =============================================================================
# STAGE 1 — SCRAPE
# =============================================================================

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
    # print("Scraping international call-ups from Wikipedia...")
    # df_international_window = load_dataset("reference", "international_windows.csv")
    # scrape_international_windows(df_international_window)


# =============================================================================
# STAGE 2 — RETRY INCOMPLETE RECORDS
# =============================================================================

def retry_incomplete_matches():
    print("\n" + "=" * 70)
    print("STAGE 2a — Retrying incomplete matches")
    print("=" * 70)

    matches_list = load_dataset("processed", "matches_list.csv")
    reg_incomplete = load_dataset("processed", "regular_season_stats_incomplete.csv")
    po_incomplete = load_dataset("processed", "playoff_stats_incomplete.csv")

    parts = [df for df in [reg_incomplete, po_incomplete] if df is not None and not df.empty]
    if not parts:
        print("No incomplete matches on file.")
        return
    all_incomplete = pd.concat(parts, ignore_index=True)

    # Backfill season/round for files saved before this column existed
    if "season" not in all_incomplete.columns or "round" not in all_incomplete.columns:
        all_incomplete = all_incomplete.drop(columns=["season", "round"], errors="ignore").merge(
            matches_list[["match_id", "season", "round"]], on="match_id", how="left"
        )

    if "status" not in all_incomplete.columns:
        all_incomplete["status"] = None
    needs_status = all_incomplete["status"].isna()
    all_incomplete.loc[needs_status, "status"] = all_incomplete.loc[needs_status].apply(
        lambda r: "confirmed_no_data" if is_confirmed_dead(r["match_id"], r["season"], r["round"])
        else "timeout_unverified",
        axis=1,
    )

    n_dead = (all_incomplete["status"] == "confirmed_no_data").sum()
    retry_ids = all_incomplete.loc[all_incomplete["status"] == "timeout_unverified", "match_id"].tolist()
    print(f"{len(all_incomplete)} incomplete matches on file: "
          f"{n_dead} confirmed_no_data (skipped), {len(retry_ids)} to retry")

    if not retry_ids:
        print("Nothing worth retrying.")
        return

    retry_matches = matches_list[matches_list["match_id"].isin(retry_ids)].copy()
    retried_stats = scrape_lnr(retry_matches, output_csv="retry_stats.csv")

    still_incomplete = load_dataset("processed", "retry_stats_incomplete.csv")
    still_incomplete_ids = set(still_incomplete["match_id"]) if still_incomplete is not None else set()
    succeeded_ids = set(retry_ids) - still_incomplete_ids
    print(f"Retry result: {len(succeeded_ids)} succeeded, {len(still_incomplete_ids)} still failing")

    # Merge successful retries back into the correct main stats file
    for is_playoff, stats_filename in [(0, "regular_season_stats.csv"), (1, "playoff_stats.csv")]:
        bucket_ids = set(
            retry_matches.loc[retry_matches["is_playoff"] == is_playoff, "match_id"]
        ) & succeeded_ids
        if not bucket_ids:
            continue
        main_stats = load_dataset("processed", stats_filename)
        main_stats = main_stats[~main_stats["match_id"].isin(bucket_ids)]
        new_rows = retried_stats[retried_stats["match_id"].isin(bucket_ids)]
        main_stats = pd.concat([main_stats, new_rows], ignore_index=True)
        save_to_csv(main_stats, stats_filename, "processed")
        print(f"  {stats_filename}: replaced {len(bucket_ids)} rows with successful retries")

    # Rewrite incomplete-tracking files: drop succeeded ids, keep the rest
    # with their existing status untouched (still-failing timeout_unverified
    # matches are NOT reclassified as confirmed_no_data without a live check)
    remaining = all_incomplete[~all_incomplete["match_id"].isin(succeeded_ids)]
    for is_playoff, incomplete_filename in [
        (0, "regular_season_stats_incomplete.csv"),
        (1, "playoff_stats_incomplete.csv"),
    ]:
        bucket_match_ids = set(matches_list.loc[matches_list["is_playoff"] == is_playoff, "match_id"])
        bucket_remaining = remaining[remaining["match_id"].isin(bucket_match_ids)]
        save_to_csv(bucket_remaining, incomplete_filename, "processed")
    print("Incomplete-tracking files updated.")


def retry_incomplete_players():
    print("\n" + "=" * 70)
    print("STAGE 2b — Retrying incomplete player profiles")
    print("=" * 70)

    player_urls = load_dataset("processed", "player_urls.csv")
    players = load_dataset("processed", "players.csv")

    player_urls["pid"] = player_urls["player_url"].apply(extract_player_id)
    players["pid"] = players["player_url"].apply(extract_player_id)
    missing_pids = set(player_urls["pid"]) - set(players["pid"])
    retry_urls = player_urls[player_urls["pid"].isin(missing_pids)][["player_url"]].drop_duplicates()

    print(f"{len(retry_urls)} player profiles missing from players.csv — retrying")
    if retry_urls.empty:
        print("Nothing to retry.")
        return

    # Seed known pre-existing failure history the first time this file is
    # created, so the manual-review threshold is correct on this retry.
    existing_incomplete = load_dataset("processed", "players_incomplete.csv")
    if existing_incomplete is None or existing_incomplete.empty:
        seed_rows = [
            {
                "player_url": url,
                "player_id": extract_player_id(url),
                "fail_count": KNOWN_PRIOR_PLAYER_FAILURES.get(extract_player_id(url), 1),
                "status": "timeout",
            }
            for url in retry_urls["player_url"]
        ]
        save_to_csv(pd.DataFrame(seed_rows), "players_incomplete.csv", "processed")
        print("Seeded players_incomplete.csv with known failure history.")

    phase2_scrape_profiles(
        retry_urls,
        output_csv="players.csv",
        incomplete_csv="players_incomplete.csv",
        resume=True,
    )


# =============================================================================
# STAGE 3 — CLEAN + FINALIZE
# =============================================================================

def dedup_players():
    print("\n" + "=" * 70)
    print("STAGE 3a — Deduplicating player URLs and players.csv")
    print("=" * 70)

    # --- player_urls.csv: dedup on canonical player_id ---
    player_urls = load_dataset("processed", "player_urls.csv")
    before_urls = len(player_urls)
    player_urls["player_id"] = player_urls["player_url"].apply(extract_player_id)
    player_urls = player_urls.drop_duplicates(subset="player_id", keep="first").drop(columns="player_id")
    save_to_csv(player_urls, "player_urls.csv", "processed")
    print(f"player_urls.csv: {before_urls} -> {len(player_urls)} rows")

    # --- players.csv: dedup on canonical player_id, after verifying agreement ---
    players = load_dataset("processed", "players.csv")
    before_players = len(players)
    players["player_id"] = players["player_url"].apply(extract_player_id)

    compare_cols = [c for c in players.columns if c not in ("player_url", "player_id")]
    dupe_ids = players.loc[players["player_id"].duplicated(keep=False), "player_id"].unique()

    mismatched_ids = set()
    for pid in dupe_ids:
        rows = players[players["player_id"] == pid]
        first = rows.iloc[0]
        for _, row in rows.iloc[1:].iterrows():
            for col in compare_cols:
                a, b = first[col], row[col]
                if not (pd.isna(a) and pd.isna(b)) and a != b:
                    mismatched_ids.add(pid)
                    break

    if mismatched_ids:
        print(f"WARNING: {len(mismatched_ids)} player_id(s) have duplicate rows that "
              f"DISAGREE on data — left untouched, flagged for manual review: "
              f"{sorted(mismatched_ids)}")
        save_to_csv(
            players[players["player_id"].isin(mismatched_ids)],
            "players_dedup_conflicts.csv",
            "processed",
        )

    safe = players[~players["player_id"].isin(mismatched_ids)]
    conflicted = players[players["player_id"].isin(mismatched_ids)]
    deduped_safe = safe.drop_duplicates(subset="player_id", keep="first")
    players_final = pd.concat([deduped_safe, conflicted], ignore_index=True)

    save_to_csv(players_final, "players.csv", "processed")
    print(f"players.csv: {before_players} -> {len(players_final)} rows "
          f"(unique player_id: {players_final['player_id'].nunique()})")

    return before_players, len(players_final)


def build_merged_matches():
    print("\n" + "=" * 70)
    print("STAGE 3b — Merging regular season + playoff stats")
    print("=" * 70)

    reg = load_dataset("processed", "regular_season_stats.csv")
    po = load_dataset("processed", "playoff_stats.csv")
    matches_list = load_dataset("processed", "matches_list.csv")

    merged = pd.concat([reg, po], ignore_index=True)
    print(f"Combined regular season ({len(reg)}) + playoff ({len(po)}) = {len(merged)} rows")

    # Attach season/round — needed for season filtering and for
    # dropped_matches_log.csv; not present in the raw stats output.
    merged = merged.merge(matches_list[["match_id", "season", "round"]], on="match_id", how="left")
    unmatched = merged["season"].isna().sum()
    if unmatched:
        print(f"WARNING: {unmatched} rows have no matching entry in matches_list.csv")

    before_filter = len(merged)
    merged = merged[merged["season"].isin(TARGET_SEASONS)].reset_index(drop=True)
    stray = before_filter - len(merged)
    if stray:
        print(f"Excluded {stray} rows outside the 5 target seasons "
              f"(stray leftovers from earlier test scrapes)")

    dup_count = merged["match_id"].duplicated().sum()
    print(f"Duplicate match_ids in merged table: {dup_count}")
    if dup_count:
        dupe_ids = sorted(merged.loc[merged["match_id"].duplicated(keep=False), "match_id"].unique())
        print(f"  WARNING — duplicated match_ids: {dupe_ids}")

    return merged


def drop_possession_columns(df):
    print("\n" + "=" * 70)
    print("STAGE 3c — Dropping unreliable general possession columns")
    print("=" * 70)
    cols = [c for c in ["home_possession", "away_possession"] if c in df.columns]
    df = df.drop(columns=cols)
    print(f"Dropped: {cols}")
    return df


def drop_bad_rows(df):
    print("\n" + "=" * 70)
    print("STAGE 3d — Dropping rows with no real data")
    print("=" * 70)

    meta_cols = {"match_id", "season", "round"}
    stat_cols = [c for c in df.columns if c not in meta_cols]
    full_count = len(stat_cols)
    nonnull_count = df[stat_cols].notna().sum(axis=1)

    # Rule A: scraper timeout — well under a full stat block
    rule_a = nonnull_count < (full_count * 0.5)
    # Rule B: LNR published no stats — checked only where Rule A didn't already catch it
    rule_b = (~rule_a) & (df["home_passes"] == 0) & (df["away_passes"] == 0)

    dropped_a = df.loc[rule_a, ["match_id", "season", "round"]].assign(reason="missing_data")
    dropped_b = df.loc[rule_b, ["match_id", "season", "round"]].assign(reason="all_zero_stats")
    dropped_log = pd.concat([dropped_a, dropped_b], ignore_index=True)
    save_to_csv(dropped_log, "dropped_matches_log.csv", "processed")

    kept = df.loc[~(rule_a | rule_b)].reset_index(drop=True)

    print(f"Rows before drop: {len(df)}")
    print(f"  Rule A (missing_data):   {int(rule_a.sum())} rows dropped")
    print(f"  Rule B (all_zero_stats): {int(rule_b.sum())} rows dropped")
    print(f"Rows after drop: {len(kept)}")

    return kept, dropped_log


def sanity_checks(rows_before_drop, final_df, dropped_log, players_before, players_after):
    print("\n" + "=" * 70)
    print("STAGE 3e — Sanity checks")
    print("=" * 70)
    print(f"Matches: {rows_before_drop} before drop -> {len(final_df)} after")
    print("Dropped by reason:")
    print(dropped_log["reason"].value_counts().to_string() if not dropped_log.empty else "  (none)")
    print(f"Players: {players_before} before dedup -> {players_after} after dedup")
    print(f"Duplicate match_ids remaining: {final_df['match_id'].duplicated().sum()}")
    print(f"Season values present: {sorted(final_df['season'].unique())}")


def main():
    scrape_all()

    retry_incomplete_matches()
    retry_incomplete_players()

    players_before, players_after = dedup_players()

    merged = build_merged_matches()
    save_to_csv(merged, "matches_stats_raw.csv", "processed")
    rows_before_drop = len(merged)

    merged = drop_possession_columns(merged)
    final_df, dropped_log = drop_bad_rows(merged)
    save_to_csv(final_df, "matches_stats_final.csv", "processed")

    sanity_checks(rows_before_drop, final_df, dropped_log, players_before, players_after)


if __name__ == "__main__":
    main()
