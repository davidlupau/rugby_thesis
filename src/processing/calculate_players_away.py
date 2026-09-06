"""
Build data/processed/players_away.csv: a per-match "absence coefficient" for
each team, capturing how much of its called-up international playing-time
importance is actually missing from that specific Top 14 fixture.

Sources (joined here):
    data/processed/international_calendar.csv
        season, round, <competition flag columns>  (1 = this round collides
        with that competition's international window, per
        build_international_calendar.py's date-buffer logic)
    data/processed/callup_name_bridge.csv
        player_name -> player_id. Only MATCHED rows are used (player_id not
        null) -- this includes every auto-matched tier plus the two hand-
        entered "manual_entry_profile_removed" rows (Timani, Takulua), whose
        LNR profile pages are gone so they never appear in players.csv.
    data/processed/player_callups.csv
        player_name, int_window_id, season, competition -- which call-up
        window(s) a name belongs to.
    data/processed/player_minutes.csv
        match_id, player_id, team, minutes_played -- actual match-by-match
        participation. This is BOTH the presence check and the sole source
        of playing-time history (players.csv is deliberately not used here).
    data/processed/matches_list.csv
        match_id -> season, round, home_team, away_team.

STEP 1 -- absence determination
--------------------------------
A round is "flagged" if international_calendar.csv has a 1 in any
competition column for that (season, round). For a flagged round, the
called-up player set is the union, over every flagged competition, of
player_callups.csv rows for that (season, competition) resolved to
player_id via the bridge (unmatched names contribute nothing).

Presence-if-played override: a called-up player is checked against
player_minutes.csv for THAT SPECIFIC match_id. If he has a minutes row
there, he is treated as present (call-up notwithstanding) and contributes
nothing. He counts as absent only when no minutes row exists for that exact
match_id.

This is deliberately match-level, not round-level, even though the flag
itself is round-level. A round can contain matches on both sides of an
international window's date buffer (see the 2025-26 round 3 case: six
matches played in September, one -- Toulon v La Rochelle -- rescheduled
into the End of Year Internationals buffer, which flags autumn_matches for
the WHOLE round). Checking presence per match_id, not per round, is what
stops that round-level noise from mislabeling players who played their
September match as absent.

A player is only "absent for" the one club he is actually on the books for.
Club affiliation per (player_id, season) is the mode of his team column in
player_minutes.csv for that season (falling back to his all-time mode team
if he has no rows at all in that season -- e.g. he was called up before/
after his only Top 14 spell in this dataset). If neither exists, or his
resolved team is neither the match's home nor away side, he is skipped
entirely for that match: he is not on either roster, so there is nothing to
attribute an absence to.

STEP 2 -- per-player weight (minutes-shrinkage)
------------------------------------------------
No prior implementation of this existed in the codebase to reuse (checked:
not in src/, not in git history). Formula as specified:

    shrunk_avg = (current_season_minutes_sum + K * prior_avg)
                 / (matches_played_so_far + K)
    weight     = shrunk_avg / 80
    K          = 5

    prior_avg: the player's OWN average minutes/match (any club) in the
    season immediately before the match's season, per SEASONS order in
    constants.py -- NOT a league-wide average.

    current_season_minutes_sum / matches_played_so_far: accumulated
    STRICTLY BEFORE the round being scored, using round-number ordering
    within the match's season (matches_list.csv carries no kickoff dates,
    so round number is the only ordering available -- see the round-3
    reschedule note above for why this can occasionally diverge from
    calendar order; the shrinkage accumulation still uses round number
    since that is how every other table in this pipeline models time).

    No prior season available -- true rookie, OR the player's first data
    point in scope is itself the current season (this includes anyone
    whose history only starts in 2021-22, the first season in SEASONS,
    since there is no season before it to look up) -- falls back to:
        weight = current_season_avg / 80
    using the SAME strictly-before-the-round current-season figures, no
    shrinkage term. If there are also zero matches played so far this
    season (first-ever appearance for this player in scope), weight = 0.0
    (no evidence of playing-time importance yet).

    Fallback-path frequency is reported by this script every run (see
    console output) rather than assumed rare.

STEP 3 -- team aggregation
----------------------------
    team_absence_coefficient = sum(weight of that team's absent, called-up
                                    players, post presence-override) / 15

Uncapped by design: tree-based models (RF/XGBoost/LightGBM) don't need
bounded inputs, and capping would discard real signal from unusually deep
call-up rounds (e.g. France). Output is two columns per match --
home_absence_coefficient / away_absence_coefficient -- not a combined
figure, since the two teams' call-up exposure is independent.

Output grain: one row per match_id in matches_list.csv (every match, not
just flagged-round ones -- unflagged rounds and matches with no resulting
absentees simply get 0.0 on both sides).

KNOWN LIMITATION -- vendor-side roster-ranking omissions in player_minutes.csv
-------------------------------------------------------------------------------
player_minutes.csv is scraped from LNR's per-match "Statistiques de tous les
joueurs" roster-ranking widget. That widget is independently confirmed
(2026-09) to sometimes omit a player from a match entirely -- not zero
minutes, no row at all -- while every teammate around him scrapes fine and
his own LNR profile page confirms he actually played. This was diagnosed by
comparing player_minutes.csv row counts against each profile page's own
matchesPlayed/minutesPlayed figures (a season-total field LNR renders on the
profile page but that this pipeline does not otherwise use or persist), for
a stratified sample of ~119 players across all five seasons. Measured
UNEXPLAINED missing-row rate (i.e. after excluding the already-known,
already-logged rounds-10-18 2022-23 gap in dropped_matches_log.csv, which
accounts for most of that one season's raw deficit):

    season       unexplained missing-row rate
    2021-2022    11.7%   (worst -- earliest-scraped season)
    2022-2023     3.6%
    2023-2024     6.2%
    2024-2025     6.2%
    2025-2026     1.5%   (best -- most recently scraped season)

This is a genuine gap in the sole data source this script uses for presence
and playing-time weight, and it inflates absence coefficients on the affected
matches (a player who actually played reads as absent, at whatever weight his
shrinkage/fallback formula assigns). It has NOT been corrected here: doing so
would mean estimating minutes rather than reading them, which is exactly the
look-ahead/estimation risk this table is designed to avoid.

Checked and ruled out: this is NOT concentrated on the call-up-bridge
population this feature actually depends on. Splitting the same ~119-player
sample by international status (call-up-bridge match vs not) shows
internationals with LOWER unexplained dropout than non-internationals
overall (4.0% vs 7.2%), and either comparable or favourable to internationals
in every season individually. The vendor gap is not a bias specific to this
feature's subject population.

Six specific players are a full-season instance of this same omission,
confirmed live against the source (fetched directly, not re-derived from
this repo's own scrape) rather than assumed:
    player_id 193    (Cubelli, RC Biarritz Olympique PB) -- season 2021-2022
    player_id 1681   (Mafi, Oyonnax Rugby)                -- season 2023-2024
    player_id 1689   (Bettencourt, Oyonnax Rugby)          -- season 2023-2024
    player_id 12214  (Sutherland, Oyonnax Rugby)           -- season 2023-2024
    player_id 2514   (Bastardie, RC Vannes)                -- season 2024-2025
    player_id 13372  (Varney, RC Vannes)                   -- season 2024-2025
Each has a confirmed nonzero matchesPlayed/minutesPlayed on his own LNR
profile page for that season, yet zero rows in player_minutes.csv for it;
re-fetching several of that player's actual match pages live reproduces the
same omission from the roster-ranking JSON directly, not just from this
repo's stored scrape. Left as a documented gap rather than patched: the
per-match minutes for these six are not recoverable from LNR's own live
source, and backfilling from a season-aggregate total (players.csv-style)
would reintroduce exactly the estimation/look-ahead risk every other row in
this table avoids.

This is the OPPOSITE failure mode from the "manual_entry_profile_removed"
tier in callup_name_bridge.csv (Timani/Takulua, player_id 11434/86): for
Timani/Takulua the match-by-match minutes data already existed correctly in
player_minutes.csv -- only the NAME-to-player_id link was broken, because
their LNR profile page has since been taken down. For the six players above,
the name/profile link is intact but the match-level minutes data was never
captured at the source in the first place. Same symptom downstream (a
called-up player who cannot be shown as present), two structurally different
causes -- worth keeping distinct if either precedent is extended later.
"""
from bisect import bisect_left

import pandas as pd

from src.constants import SEASONS
from src.processing.build_international_calendar import (
    COMPETITION_COLUMNS,
    FLAG_COLUMNS,
)
from src.utils import load_dataset, save_to_csv

K_SHRINKAGE = 5
FULL_MATCH_MINUTES = 80
SQUAD_SIZE = 15

# competition flag column -> competition name, as used in player_callups.csv
# / international_windows.csv. Reuses the exact mapping
# build_international_calendar.py already uses, rather than redefining it.
FLAG_TO_COMPETITION = {col: comp for comp, col in COMPETITION_COLUMNS.items()}


def _build_called_up_lookup(callups: pd.DataFrame, bridge: pd.DataFrame) -> dict:
    """(season, competition) -> set of player_id, matched bridge rows only."""
    matched = bridge[bridge["player_id"].notna()][["player_name", "player_id"]].copy()
    matched["player_id"] = matched["player_id"].astype(int)

    merged = callups.merge(matched, on="player_name", how="inner")
    merged = merged.drop_duplicates(subset=["player_id", "season", "competition"])

    lookup: dict[tuple[str, str], set[int]] = {}
    for (season, competition), grp in merged.groupby(["season", "competition"]):
        lookup[(season, competition)] = set(grp["player_id"])
    return lookup


def _build_season_history(pm: pd.DataFrame) -> tuple[dict, dict]:
    """
    From player_minutes.csv (joined to matches_list for season/round):
        rounds_by_player_season[(pid, season)] -> [(round, minutes), ...] sorted
        season_avg[(pid, season)]               -> mean minutes/match that season
    """
    rounds_by_player_season: dict[tuple[int, str], list[tuple[int, float]]] = {}
    season_avg: dict[tuple[int, str], float] = {}

    for (pid, season), grp in pm.groupby(["player_id", "season"]):
        ordered = sorted(zip(grp["round"], grp["minutes_played"]))
        rounds_by_player_season[(pid, season)] = ordered
        season_avg[(pid, season)] = float(grp["minutes_played"].mean())

    return rounds_by_player_season, season_avg


def _sum_before_round(rounds_by_player_season: dict, pid: int, season: str,
                       round_: int) -> tuple[float, int]:
    """Sum/count of minutes played strictly before `round_`, this season."""
    entries = rounds_by_player_season.get((pid, season))
    if not entries:
        return 0.0, 0
    rounds = [r for r, _ in entries]
    idx = bisect_left(rounds, round_)
    before = entries[:idx]
    if not before:
        return 0.0, 0
    total = sum(mins for _, mins in before)
    return float(total), len(before)


def _build_team_lookup(pm: pd.DataFrame) -> tuple[dict, dict]:
    """
    (pid, season) -> most common team that season; pid -> most common team
    across all seasons (fallback for a season with zero appearances).
    """
    by_season = (
        pm.groupby(["player_id", "season"])["team"]
        .agg(lambda s: s.mode().iat[0])
        .to_dict()
    )
    overall = (
        pm.groupby("player_id")["team"]
        .agg(lambda s: s.mode().iat[0])
        .to_dict()
    )
    return by_season, overall


def calculate_players_away() -> pd.DataFrame:
    calendar = load_dataset("processed", "international_calendar.csv")
    bridge = load_dataset("processed", "callup_name_bridge.csv")
    callups = load_dataset("processed", "player_callups.csv")
    minutes = load_dataset("processed", "player_minutes.csv")
    matches = load_dataset("processed", "matches_list.csv")

    pm = minutes.merge(matches[["match_id", "season", "round"]], on="match_id", how="left")

    presence = set(zip(minutes["player_id"], minutes["match_id"]))
    called_up_lookup = _build_called_up_lookup(callups, bridge)
    rounds_by_player_season, season_avg = _build_season_history(pm)
    team_by_season, team_overall = _build_team_lookup(pm)

    calendar_lookup = {
        (row["season"], int(row["round"])): row for _, row in calendar.iterrows()
    }

    path_counts = {"shrinkage": 0, "fallback_current": 0, "fallback_zero": 0}
    skipped_no_team = 0
    skipped_wrong_team = 0

    results = []
    for _, m in matches.iterrows():
        season, round_ = m["season"], int(m["round"])
        match_id, home, away = m["match_id"], m["home_team"], m["away_team"]

        cal_row = calendar_lookup.get((season, round_))
        flagged = [FLAG_TO_COMPETITION[c] for c in FLAG_COLUMNS
                   if cal_row is not None and cal_row[c] == 1]

        home_weights: list[float] = []
        away_weights: list[float] = []

        if flagged:
            called = set()
            for comp in flagged:
                called |= called_up_lookup.get((season, comp), set())

            for pid in called:
                if (pid, match_id) in presence:
                    continue  # present-if-played override

                team = team_by_season.get((pid, season)) or team_overall.get(pid)
                if team is None:
                    skipped_no_team += 1
                    continue
                if team == home:
                    side = home_weights
                elif team == away:
                    side = away_weights
                else:
                    skipped_wrong_team += 1
                    continue

                sum_before, cnt_before = _sum_before_round(
                    rounds_by_player_season, pid, season, round_
                )

                season_idx = SEASONS.index(season)
                prior_season = SEASONS[season_idx - 1] if season_idx > 0 else None
                prior_avg = season_avg.get((pid, prior_season)) if prior_season else None

                if prior_avg is not None:
                    shrunk = (sum_before + K_SHRINKAGE * prior_avg) / (cnt_before + K_SHRINKAGE)
                    weight = shrunk / FULL_MATCH_MINUTES
                    path_counts["shrinkage"] += 1
                elif cnt_before > 0:
                    weight = (sum_before / cnt_before) / FULL_MATCH_MINUTES
                    path_counts["fallback_current"] += 1
                else:
                    weight = 0.0
                    path_counts["fallback_zero"] += 1

                side.append(weight)

        results.append({
            "match_id": match_id,
            "season": season,
            "round": round_,
            "home_team": home,
            "away_team": away,
            "home_absence_coefficient": sum(home_weights) / SQUAD_SIZE,
            "away_absence_coefficient": sum(away_weights) / SQUAD_SIZE,
        })

    out = pd.DataFrame(results)

    total_weighted = sum(path_counts.values())
    print("=" * 72)
    print(f"absence-instance weight paths (n={total_weighted}):")
    for path, n in path_counts.items():
        pct = n / total_weighted if total_weighted else 0.0
        print(f"  {path:<18}{n:6d}  ({pct:5.1%})")
    fallback_n = path_counts["fallback_current"] + path_counts["fallback_zero"]
    fallback_pct = fallback_n / total_weighted if total_weighted else 0.0
    print(f"  -> no-prior-season fallback used for {fallback_n}/{total_weighted} "
          f"absence instances ({fallback_pct:.1%})")
    print(f"skipped (no resolvable club team)      : {skipped_no_team}")
    print(f"skipped (team not in this fixture)     : {skipped_wrong_team}")
    print(f"matches with a flagged round           : "
          f"{int((out[['home_absence_coefficient','away_absence_coefficient']].sum(axis=1) > 0).sum())}"
          f" nonzero / {len(out)} total")
    print("=" * 72)

    save_to_csv(out, "players_away.csv", "processed")
    return out


if __name__ == "__main__":
    calculate_players_away()
