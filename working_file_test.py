"""
Retry pass for the players still missing from players.csv
========================================================
After the main scrape (build_dataset.py ->
scrape_lnr_players.scrape_player_registry) 31 player profiles never made it
into data/processed/players.csv. They are the gap between:

    player_urls.csv  — every player seen in a Top 14 target-season match roster
    players.csv      — every profile that scraped successfully

i.e. any player_id present in player_urls.csv but absent from players.csv.
Those same 31 are logged in data/processed/players_incomplete.csv with
fail_count == 4 / status "manual_review_needed".

This script retries those 31 profiles ONCE, using the SAME per-profile routine
the original run used for every player — no new extraction method:

    scrape_lnr_players.scrape_player_profile(driver, url, delay)
        -> get_soup_simple()        load page, wait for player-heading,
                                    expand the full career-history table
        -> parse_player_name()      identity
        -> extract_nationality()    flag alt text
        -> extract_career_data()    season-by-season Top 14 team + avg minutes

On success -> the player's row (first/last/full name, nationality, and for each
              target season the team + avg minutes) is appended to players.csv
              with the exact same columns as the rest of the file, player_id
              included.

On failure -> the player stays in players_incomplete.csv with fail_count bumped
              by one and `last_error` set to the SPECIFIC reason this attempt
              failed instead of a generic "manual_review_needed", so a second
              retry attempt starts with more to go on:
                profile_removed_redirect_to[...]  the profile path now
                    302-redirects to /joueurs on both prod2 and top14 hosts —
                    the page has been taken down; re-scraping cannot recover it
                page_not_rendered / missing_career_section /
                404_or_missing_profile / identity_not_extracted / a WebDriver
                    exception name  — the other, rarer cases

Reads:   data/processed/player_urls.csv
         data/processed/players.csv
         data/processed/players_incomplete.csv   (prior fail_count; optional)
Writes:  data/processed/players.csv              (resolved rows appended)
         data/processed/players_incomplete.csv   (still-failing rows only)

Does NOT touch callup_name_bridge.csv and does NOT re-run the name bridge.

    python working_file_test.py

OUTCOME OF THE 2026-09-04 RUN
----------------------------
0 of 31 resolved. Every one of the 31 profile URLs now 302-redirects to
/joueurs (the player index) on BOTH prod2.lnr.fr and top14.lnr.fr — the
profile pages have been permanently removed from LNR, which is why they
failed four times in the original run (not transient timeouts). Verified
independently with a plain HTTP probe before the Selenium pass.

players.csv was left unchanged. players_incomplete.csv was rewritten with the
specific reason on every row: fail_count 4 -> 5,
last_error = "profile_removed_redirect_to[https://prod2.lnr.fr/joueurs]".

Follow-up (done outside this script): 2 of the 31 are confirmed international
call-ups whose absence feature needs them — Lopeti Timani (11434) and
Sonatane Takulua (86). Both have Top 14 appearances in player_minutes.csv and
call-ups in player_callups.csv, so they were matched to their player_id by
hand directly in callup_name_bridge.csv (match_method
"manual_entry_profile_removed"), bypassing players.csv entirely — see the
docstring of src/processing/build_callup_name_bridge.py. The remaining 27
stay in players_incomplete.csv as permanently unresolved: same 302-removed
pages, but none is a call-up the analysis depends on.
"""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

from src.utils import extract_player_id, save_to_csv
from src.collection.scrape_lnr_players import (
    init_driver,
    scrape_player_profile,
    TARGET_SEASONS,
)

try:
    from selenium.common.exceptions import TimeoutException, WebDriverException
except ImportError:  # keep the module importable even without selenium present
    class TimeoutException(Exception):
        ...

    class WebDriverException(Exception):
        ...


pd.set_option("display.width", 200)

PROCESSED = Path(__file__).parent / "data" / "processed"
PLAYERS_CSV = PROCESSED / "players.csv"
PLAYER_URLS_CSV = PROCESSED / "player_urls.csv"
INCOMPLETE_CSV = PROCESSED / "players_incomplete.csv"

# Seconds to wait before each page load. These 31 profiles have already timed
# out four times each, so give the page a little more room than phase 2's 1.5s.
DELAY = 2.5

INCOMPLETE_COLUMNS = [
    "player_url", "player_id", "fail_count", "last_error", "last_attempt_utc",
]

# The four confirmed international call-ups — reported by name at the end
# because the absence feature depends on them most.
KEY_CALLUPS = {
    "11434": "Lopeti Timani",
    "1781": "Sitaleki Timani",
    "2678": "Torsten Van Jaarsveld",
    "86": "Sonatane Takulua",
}
VAN_JAARSVELD_ID = "2678"


# =============================================================================
# BUILD THE RETRY LIST  (gap between player_urls.csv and players.csv)
# =============================================================================

def build_retry_list():
    """
    Return (todo, players_df, columns) where todo is a list of
    (player_id, player_url, prior_fail_count) for every player_id present in
    player_urls.csv but absent from players.csv.
    """
    urls = pd.read_csv(PLAYER_URLS_CSV)
    players = pd.read_csv(PLAYERS_CSV)

    urls["pid"] = urls["player_url"].map(extract_player_id)
    have = {extract_player_id(u) for u in players["player_url"].dropna()}
    have.discard(None)

    gap = (
        urls[urls["pid"].notna() & ~urls["pid"].isin(have)]
        .drop_duplicates(subset="pid", keep="first")
        .sort_values("pid", key=lambda s: s.astype(int))
    )

    # Prior fail_count from the incomplete log, keyed by player_id.
    prior = {}
    logged_ids = set()
    if INCOMPLETE_CSV.exists():
        inc = pd.read_csv(INCOMPLETE_CSV)
        for _, r in inc.iterrows():
            pid = str(r["player_id"])
            logged_ids.add(pid)
            prior[pid] = int(r["fail_count"]) if pd.notna(r.get("fail_count")) else 0

    gap_ids = set(gap["pid"])
    if logged_ids and logged_ids != gap_ids:
        print("  note: players_incomplete.csv and the reconstructed gap differ "
              "— using the gap as the source of truth")
        if logged_ids - gap_ids:
            print(f"    in log but not in gap: {sorted(logged_ids - gap_ids)}")
        if gap_ids - logged_ids:
            print(f"    in gap but not in log: {sorted(gap_ids - logged_ids)}")

    todo = [
        (str(row.pid), str(row.player_url), prior.get(str(row.pid), 0))
        for row in gap.itertuples()
    ]
    return todo, players, list(players.columns)


# =============================================================================
# PER-PROFILE RETRY
# =============================================================================

def diagnose(record, soup, exc_note, requested_url, final_url):
    """
    Classify why this attempt did not produce a usable row. Returns a specific
    reason string, or None when the profile scraped fine (identity + a rendered
    career table — season data may still be legitimately empty, exactly like
    the ~20 all-blank rows already in players.csv).

    Inspects the post-load URL and the DOM still loaded in the driver — no
    second fetch, no new extraction logic.

    The dominant case for these 31: LNR now answers the profile path with a
    hard 302 to /joueurs (the player index) on both prod2 and top14 hosts —
    the profile page has been removed from the live site. That is a settled
    "gone", not a transient timeout, so it gets its own reason and no amount
    of re-scraping this path will recover it.
    """
    req_id = extract_player_id(requested_url)
    landed = (final_url or "").rstrip("/")
    if req_id and landed and f"/joueur/{req_id}-" not in landed and "/joueur/" not in landed:
        return f"profile_removed_redirect_to[{landed}]"

    if soup is None:
        return exc_note or "browser_error_no_page_source"

    title = soup.title.get_text(strip=True) if soup.title else ""
    heading = soup.find(class_=lambda c: c and "player-heading" in str(c))
    career = soup.find("div", class_="history-season-list")
    tl = title.lower()
    looks_404 = any(m in tl for m in ("404", "not found", "introuvable", "erreur"))

    if heading is None:
        if looks_404:
            return "404_or_missing_profile"
        return f"page_not_rendered ({exc_note})" if exc_note else "page_not_rendered"
    if not (record and record.get("full_name")):
        return "identity_not_extracted"
    if career is None:
        return "missing_career_section"
    return None


def row_from_record(record, pid, columns):
    """Shape a scraped record into a players.csv row in the file's column order."""
    row = {c: record.get(c) for c in columns}
    row["player_url"] = record.get("player_url")
    row["player_id"] = int(pid)
    return row


def retry_profiles(todo):
    """
    Run one retry pass over `todo`. Returns (resolved, failed, attempted):
        resolved  : {pid -> scraped record dict}
        failed    : {pid -> specific reason string}
        attempted : set of pids actually tried this run
    """
    resolved, failed, attempted = {}, {}, set()

    driver = init_driver(headless=True)
    try:
        for i, (pid, url, prior_fc) in enumerate(todo, start=1):
            print(f"[{i:>2}/{len(todo)}] {pid:>6}  {url}")
            attempted.add(pid)

            record, exc_note = None, ""
            try:
                record = scrape_player_profile(driver, url, DELAY)
            except (TimeoutException, WebDriverException) as exc:
                exc_note = type(exc).__name__
            except Exception as exc:  # noqa: BLE001 - want the reason, not a crash
                exc_note = f"error:{type(exc).__name__}"

            try:
                html = driver.page_source or ""
            except Exception:  # noqa: BLE001
                html = ""
            try:
                final_url = driver.current_url
            except Exception:  # noqa: BLE001
                final_url = ""
            soup = BeautifulSoup(html, "html.parser") if html else None

            reason = diagnose(record, soup, exc_note, url, final_url)
            if reason is None:
                resolved[pid] = record
                hits = [s for s in TARGET_SEASONS if record.get(f"{s}_team")]
                print(f"         -> RESOLVED  {record.get('full_name', '?')} "
                      f"({record.get('nationality', '?')})  "
                      f"Top 14 seasons: {', '.join(hits) if hits else 'none (blank row)'}")
            else:
                failed[pid] = reason
                print(f"         -> STILL FAILING  fail_count {prior_fc}->{prior_fc + 1}"
                      f"  reason: {reason}")
    finally:
        driver.quit()
        print("\nWebDriver closed")

    return resolved, failed, attempted


# =============================================================================
# PERSIST
# =============================================================================

def write_outputs(todo, players, columns, resolved, failed, attempted, run_ts):
    """Append resolved rows to players.csv; rewrite players_incomplete.csv."""
    if resolved:
        new_rows = pd.DataFrame(
            [row_from_record(rec, pid, columns) for pid, rec in resolved.items()],
            columns=columns,
        )
        players_out = pd.concat([players, new_rows], ignore_index=True)
        players_out["player_id"] = players_out["player_id"].astype("int64")
        save_to_csv(players_out, "players.csv", "processed")
    else:
        players_out = players
        print("No profiles resolved — players.csv left unchanged.")

    inc_rows = []
    for pid, url, prior_fc in todo:
        if pid in resolved:
            continue
        if pid in failed:
            inc_rows.append({
                "player_url": url,
                "player_id": int(pid),
                "fail_count": prior_fc + 1,
                "last_error": failed[pid],
                "last_attempt_utc": run_ts,
            })
        else:  # pass aborted before this one was reached
            inc_rows.append({
                "player_url": url,
                "player_id": int(pid),
                "fail_count": prior_fc,
                "last_error": "not_reached_this_run",
                "last_attempt_utc": run_ts,
            })
    inc_df = pd.DataFrame(inc_rows, columns=INCOMPLETE_COLUMNS)
    save_to_csv(inc_df, "players_incomplete.csv", "processed")

    return players_out, inc_df


# =============================================================================
# SUMMARY
# =============================================================================

def _season_line(rec):
    parts = []
    for s in TARGET_SEASONS:
        team = rec.get(f"{s}_team") or "—"
        mins = rec.get(f"{s}_avg_min")
        mins = "—" if mins is None or (isinstance(mins, float) and pd.isna(mins)) else mins
        parts.append(f"{s}: {team} ({mins})")
    return "\n        ".join(parts)


def print_summary(todo, resolved, failed, attempted):
    prior_by_pid = {pid: fc for pid, _, fc in todo}

    print("\n" + "=" * 80)
    print("RETRY SUMMARY")
    print("=" * 80)
    print(f"  retried:       {len(todo)}")
    print(f"  resolved:      {len(resolved)}  (rows appended to players.csv)")
    print(f"  still failing: {len(failed) + (len(todo) - len(attempted))}"
          f"  (rows in players_incomplete.csv)")

    if resolved:
        print("\n  RESOLVED")
        print("  " + "-" * 76)
        for pid, rec in sorted(resolved.items(), key=lambda kv: int(kv[0])):
            hits = [s for s in TARGET_SEASONS if rec.get(f"{s}_team")]
            tag = "/".join(h[:7] for h in hits) if hits else "no Top 14 target-season rows (blank row)"
            print(f"    {pid:>6}  {(rec.get('full_name') or '?'):32}  "
                  f"{(rec.get('nationality') or '?'):18}  {tag}")

    if failed or len(todo) != len(attempted):
        print("\n  STILL FAILING")
        print("  " + "-" * 76)
        for pid, url, prior_fc in todo:
            if pid in resolved:
                continue
            reason = failed.get(pid, "not_reached_this_run")
            fc = prior_fc + 1 if pid in failed else prior_fc
            print(f"    {pid:>6}  fail_count={fc}  {reason}")
        print("\n  failure reasons")
        print("  " + "-" * 76)
        tally = Counter(failed.values())
        for reason, n in tally.most_common():
            print(f"    {n:>2}  {reason}")
        missed = len(todo) - len(attempted)
        if missed:
            print(f"    {missed:>2}  not_reached_this_run")

        n_removed = sum(1 for r in failed.values() if r.startswith("profile_removed"))
        if n_removed:
            print(f"\n  NOTE: {n_removed}/{len(todo)} failures are profile_removed — the LNR "
                  "profile path now 302-redirects to /joueurs on both hosts, i.e. the page\n"
                  "  no longer exists. Re-running this scrape will not recover them; their "
                  "identity / nationality / minutes would have to come from another source\n"
                  "  (Wayback Machine snapshot, the cross-reference workbook, or manual entry).")

    # --- the four international call-ups -----------------------------------
    print("\n  KEY INTERNATIONAL CALL-UPS  (matter most for the absence feature)")
    print("  " + "-" * 76)
    for pid, name in KEY_CALLUPS.items():
        if pid in resolved:
            rec = resolved[pid]
            print(f"    {name} ({pid}): RESOLVED  — nationality {rec.get('nationality', '?')}")
            print(f"        {_season_line(rec)}")
        elif pid in failed:
            fc = prior_by_pid.get(pid, 0) + 1
            print(f"    {name} ({pid}): STILL FAILING  (fail_count={fc}, {failed[pid]})")
        elif pid not in attempted and pid in prior_by_pid:
            print(f"    {name} ({pid}): NOT REACHED this run")
        else:
            print(f"    {name} ({pid}): not in the retry set "
                  f"(already in players.csv or not in player_urls.csv)")

    # --- Van Jaarsveld 2023-24 question ----------------------------------
    print("\n  TORSTEN VAN JAARSVELD (2678) — 2023-24 season check")
    print("  " + "-" * 76)
    if VAN_JAARSVELD_ID in resolved:
        rec = resolved[VAN_JAARSVELD_ID]
        t2324 = rec.get("2023-2024_team")
        m2324 = rec.get("2023-2024_avg_min")
        has_2324 = bool(t2324) or (m2324 is not None and not (isinstance(m2324, float) and pd.isna(m2324)))
        print(f"        {_season_line(rec)}")
        if has_2324:
            print(f"    -> 2023-24 DATA PRESENT: {t2324} / avg {m2324} min. "
                  f"The mid-career gap is closed by this retry.")
        else:
            print("    -> NO 2023-24 data surfaced. He has real minutes in 2022-23 and "
                  "2024-25 but the retry still shows nothing in 2023-24 — the profile's "
                  "career-history table has no Top 14 row for that season, so the gap is "
                  "real on LNR's side, not a scrape miss.")
    elif VAN_JAARSVELD_ID in failed:
        fc = prior_by_pid.get(VAN_JAARSVELD_ID, 0) + 1
        reason = failed[VAN_JAARSVELD_ID]
        print(f"    Profile not scraped (fail_count={fc}, {reason}).")
        if reason.startswith("profile_removed"):
            print("    His LNR profile page has been removed (302 -> /joueurs), so the "
                  "career-history table — and with it any 2023-24 row — is no longer\n"
                  "    served by LNR at all. The 2023-24 question can't be answered from this "
                  "source; it needs a Wayback snapshot of the profile or another dataset.")
        else:
            print("    The 2023-24 question cannot be answered until the profile page renders.")
    else:
        print("    Not reached this run — cannot report on 2023-24 data.")


# =============================================================================
# ENTRY POINT
# =============================================================================

def main():
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    print("=" * 80)
    print("RETRY PASS — players missing from players.csv")
    print("=" * 80)

    todo, players, columns = build_retry_list()
    print(f"  {len(todo)} players to retry "
          f"(gap between player_urls.csv and players.csv)\n")
    if not todo:
        print("Nothing to retry — players.csv already covers every player URL.")
        return

    resolved, failed, attempted = retry_profiles(todo)
    write_outputs(todo, players, columns, resolved, failed, attempted, run_ts)
    print_summary(todo, resolved, failed, attempted)


if __name__ == "__main__":
    main()
