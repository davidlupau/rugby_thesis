"""
Retry incomplete matches and player profiles from a prior scrape_lnr.py /
scrape_lnr_players.py run.

retry_incomplete_matches()
    Retries timeout_unverified matches (confirmed_no_data matches are
    considered settled and excluded by default — see
    src/constants.py::is_confirmed_dead and NO_STATS_TEXT in scrape_lnr.py
    for how that status actually gets assigned). Which matches time out
    varies run to run (server load, network conditions, browser session
    state), so this runs several retry passes in sequence by default,
    each one re-checking what's still failing and retrying again — a
    single pass is not treated as final. Each still-incomplete match keeps
    whatever status THAT pass's own attempt produced; nothing is inferred
    from a previous pass or from other matches.

    Pass include_confirmed_dead=True for an explicit one-off pass that also
    re-attempts currently-confirmed_no_data matches, to check whether any
    were mislabeled. This is opt-in only — never run automatically.

retry_incomplete_players()
    Retries player profile URLs missing from players.csv, tracking
    fail_count per player across runs; anything failing 3+ times is flagged
    manual_review_needed instead of a generic timeout.
"""
import pandas as pd

from src.utils import load_dataset, save_to_csv, extract_player_id
from src.collection.scrape_lnr import scrape_lnr
from src.collection.scrape_lnr_players import phase2_scrape_profiles
from src.constants import is_confirmed_dead

# Known failure history that predates the fail_count tracking in
# phase2_scrape_profiles — used only to seed players_incomplete.csv the
# first time it's created, so the manual-review threshold is correct.
KNOWN_PRIOR_PLAYER_FAILURES = {"2019": 2}  # alexandre-perez: failed twice already


def _run_one_match_retry_pass(matches_list, include_confirmed_dead):
    """
    One retry attempt over the current incomplete-tracking files.
    Returns True if any matches were retried this pass, False otherwise
    (nothing left to retry, so the caller should stop looping).
    """
    reg_incomplete = load_dataset("processed", "regular_season_stats_incomplete.csv")
    po_incomplete = load_dataset("processed", "playoff_stats_incomplete.csv")

    parts = [df for df in [reg_incomplete, po_incomplete] if df is not None and not df.empty]
    if not parts:
        print("No incomplete matches on file.")
        return False
    all_incomplete = pd.concat(parts, ignore_index=True)

    # Backfill season/round/status only for legacy files saved before these
    # columns existed. Uses is_confirmed_dead(match_id) alone — a purely
    # per-match, individually-verified check, never season/round-based.
    if "season" not in all_incomplete.columns or "round" not in all_incomplete.columns:
        all_incomplete = all_incomplete.drop(columns=["season", "round"], errors="ignore").merge(
            matches_list[["match_id", "season", "round"]], on="match_id", how="left"
        )
    if "status" not in all_incomplete.columns:
        all_incomplete["status"] = None
    needs_status = all_incomplete["status"].isna()
    all_incomplete.loc[needs_status, "status"] = all_incomplete.loc[needs_status, "match_id"].apply(
        lambda mid: "confirmed_no_data" if is_confirmed_dead(mid) else "timeout_unverified"
    )

    statuses_to_retry = {"timeout_unverified"}
    if include_confirmed_dead:
        statuses_to_retry.add("confirmed_no_data")

    n_dead = (all_incomplete["status"] == "confirmed_no_data").sum()
    retry_ids = all_incomplete.loc[all_incomplete["status"].isin(statuses_to_retry), "match_id"].tolist()
    print(f"{len(all_incomplete)} incomplete matches on file: "
          f"{n_dead} confirmed_no_data, {len(retry_ids)} queued for retry this pass")

    if not retry_ids:
        print("Nothing worth retrying.")
        return False

    retry_matches = matches_list[matches_list["match_id"].isin(retry_ids)].copy()
    retried_stats = scrape_lnr(retry_matches, output_csv="retry_stats.csv")

    still_incomplete = load_dataset("processed", "retry_stats_incomplete.csv")
    if still_incomplete is not None and not still_incomplete.empty:
        still_incomplete_ids = set(still_incomplete["match_id"])
        # Status as determined by THIS attempt only — used below instead of
        # carrying over whatever status the match had before this pass.
        fresh_status_by_id = dict(zip(still_incomplete["match_id"], still_incomplete["status"]))
    else:
        still_incomplete_ids = set()
        fresh_status_by_id = {}
    succeeded_ids = set(retry_ids) - still_incomplete_ids
    n_freshly_verified_empty = sum(1 for s in fresh_status_by_id.values() if s == "confirmed_no_data")
    print(f"Retry result: {len(succeeded_ids)} succeeded, {len(still_incomplete_ids)} still incomplete "
          f"({n_freshly_verified_empty} of those freshly verified empty this attempt)")

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

    # Rewrite incomplete-tracking files:
    #   - succeeded ids are dropped entirely
    #   - ids retried this pass but still incomplete adopt THIS pass's own
    #     status (never a stale one carried over from before)
    #   - ids not retried this pass (e.g. confirmed_no_data when
    #     include_confirmed_dead=False) keep their existing status untouched
    remaining = all_incomplete[~all_incomplete["match_id"].isin(succeeded_ids)].copy()
    retried_this_pass = remaining["match_id"].isin(retry_ids)
    remaining.loc[retried_this_pass, "status"] = remaining.loc[retried_this_pass, "match_id"].map(
        lambda mid: fresh_status_by_id.get(mid, "timeout_unverified")
    )

    for is_playoff, incomplete_filename in [
        (0, "regular_season_stats_incomplete.csv"),
        (1, "playoff_stats_incomplete.csv"),
    ]:
        bucket_match_ids = set(matches_list.loc[matches_list["is_playoff"] == is_playoff, "match_id"])
        bucket_remaining = remaining[remaining["match_id"].isin(bucket_match_ids)]
        save_to_csv(bucket_remaining, incomplete_filename, "processed")
    print("Incomplete-tracking files updated.")

    return True


def retry_incomplete_matches(include_confirmed_dead: bool = False, max_passes: int = 3):
    """
    Args:
        include_confirmed_dead: if True, also re-attempts matches currently
            marked confirmed_no_data, to re-verify whether that label still
            holds. Opt-in only — call this explicitly for a one-off
            re-verification pass, never as part of the default flow.
        max_passes: retry rounds to run in sequence. Each pass re-checks
            what's still timeout_unverified and retries again; stops early
            once a pass has nothing left to retry.
    """
    print("\n" + "=" * 70)
    print("Retrying incomplete matches")
    print("=" * 70)

    matches_list = load_dataset("processed", "matches_list.csv")
    for pass_num in range(1, max_passes + 1):
        print(f"\n--- Retry pass {pass_num}/{max_passes} ---")
        attempted = _run_one_match_retry_pass(matches_list, include_confirmed_dead)
        if not attempted:
            break


def retry_incomplete_players():
    print("\n" + "=" * 70)
    print("Retrying incomplete player profiles")
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
