"""
Clean the match-level and player-level datasets, after scraping (and any
retries) have produced the raw CSVs in data/processed/. This is one stage
of processing, not the last one — weather and other contextual features are
added on top of this output in later steps.

dedup_players()
    LNR serves the same player from multiple domains (prod2.lnr.fr /
    top14.lnr.fr) with the same numeric ID. Dedups player_urls.csv and
    players.csv on that canonical player_id instead of the full URL string.
    Duplicate rows are verified to agree on name/nationality/season stats
    before being dropped; any that disagree are flagged instead of silently
    dropped (see players_dedup_conflicts.csv if that file appears).

build_merged_matches()
    Merges regular season + playoff stats into one table, restricted to
    the 5 target seasons (excludes stray 2017-2018/2018-2019 test-scrape rows).

drop_possession_columns()
    Drops the unreliable general home/away_possession columns (flat 50/50
    before ~15 April 2023, when LNR wasn't tracking the stat).

drop_bad_rows()
    Drops rows with no real data, logging every drop to
    dropped_matches_log.csv:
      Rule A (missing_data):    scraper timeout, <50% of stat fields populated
      Rule B (all_zero_stats):  home_passes == 0 and away_passes == 0
                                 (LNR published no stats for the match)

sanity_checks()
    Prints before/after row counts, drop counts, and dedup counts.

Output: data/processed/matches_stats_raw.csv, matches_stats_final.csv,
        dropped_matches_log.csv
"""
import pandas as pd

from src.utils import load_dataset, save_to_csv, extract_player_id
from src.constants import SEASONS as TARGET_SEASONS


def dedup_players():
    print("\n" + "=" * 70)
    print("Deduplicating player URLs and players.csv")
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
    print("Merging regular season + playoff stats")
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
    print("Dropping unreliable general possession columns")
    print("=" * 70)
    cols = [c for c in ["home_possession", "away_possession"] if c in df.columns]
    df = df.drop(columns=cols)
    print(f"Dropped: {cols}")
    return df


def drop_bad_rows(df):
    print("\n" + "=" * 70)
    print("Dropping rows with no real data")
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
    print("Sanity checks")
    print("=" * 70)
    print(f"Matches: {rows_before_drop} before drop -> {len(final_df)} after")
    print("Dropped by reason:")
    print(dropped_log["reason"].value_counts().to_string() if not dropped_log.empty else "  (none)")
    print(f"Players: {players_before} before dedup -> {players_after} after dedup")
    print(f"Duplicate match_ids remaining: {final_df['match_id'].duplicated().sum()}")
    print(f"Season values present: {sorted(final_df['season'].unique())}")
