"""
Build data/processed/international_calendar.csv: a per-(season, round) table
of Top 14 rounds that collide with a major international window, one flag
column per competition.

Sources (joined here):
    data/reference/international_windows.csv
        int_window_id, season, competition, start_date, end_date, url
        Dates are ISO (YYYY-MM-DD). Some 2025-2026 rows still have blank
        start/end dates.
    data/processed/matches_list.csv
        match_id, season, round, venue, home_team, away_team, url, is_playoff
        The fixture list — has no dates.
    data/processed/matches_stats_final.csv
        match_id, match_date, ... — supplies the date for each match.

matches_list is joined to matches_stats_final on match_id to attach a date
to every match, and from there a set of dates to every (season, round).

Flag logic:
    For each international window, a round is flagged 1 if ANY match in that
    round kicks off within [start_date - 14 days, end_date + 7 days] — the
    standard buffer. Each competition is evaluated independently, so
    overlapping windows (e.g. 2024-2025 Rugby Championship and Pacific Cup)
    can both flag the same round in their respective columns.

    Exception — 2023 Rugby World Cup (season 2023-2024): the date buffer is
    NOT used. Rounds 1-3 are hardcoded as flagged. The Top 14 season paused
    entirely after round 3 that year and resumed the day after the World Cup
    final; this is confirmed against LNR's published calendar and against
    zero-minutes appearances for 8 known France WC squad members in
    player_minutes.csv.

Output columns:
    season, round, rugby_championship, autumn_matches, 6nations,
    pacific_cup, world_cup
    (No european_congestion — that is a separate feature/script.)

Missing data is warned about, never fatal:
    - windows with blank start/end dates flag nothing;
    - matches with no date after the join contribute to nothing.

Known limitation (expected, not an open gap): the matches that get no date
after the join are exactly the set logged in
data/processed/dropped_matches_log.csv — the 70 matches excluded during
match-stats collection for missing_data / all_zero_stats (verified identical,
both directions). They are absent from matches_stats_final.csv by design, so
they carry no date here. The practical effect is that 2022-2023 rounds 11-18
(60 of those 70) have zero dated matches, so any international window that
overlaps only that span (e.g. the 2023 Six Nations) is under-flagged for
those rounds until those match dates are sourced elsewhere.
"""
from datetime import timedelta

import pandas as pd

from src.utils import load_dataset, save_to_csv

# international_windows.csv competition value -> output flag column.
COMPETITION_COLUMNS = {
    "Rugby Championship": "rugby_championship",
    "End of Year Internationals": "autumn_matches",
    "6 Nations": "6nations",
    "Pacific Cup": "pacific_cup",
    "World cup": "world_cup",
}

# Output flag columns, in output order.
FLAG_COLUMNS = [
    "rugby_championship",
    "autumn_matches",
    "6nations",
    "pacific_cup",
    "world_cup",
]

# Standard buffer around a window, in days.
PRE_BUFFER_DAYS = 14
POST_BUFFER_DAYS = 7

# Hardcoded exception (see module docstring): 2023 Rugby World Cup.
WORLD_CUP_2023_SEASON = "2023-2024"
WORLD_CUP_2023_ROUNDS = {1, 2, 3}


def _attach_match_dates(matches_list: pd.DataFrame,
                        match_stats: pd.DataFrame) -> pd.DataFrame:
    """Join matches_list -> match_stats on match_id; parse match_date."""
    dated = matches_list.merge(
        match_stats[["match_id", "match_date"]], on="match_id", how="left"
    )
    dated["match_date"] = pd.to_datetime(dated["match_date"], errors="coerce")

    missing = dated[dated["match_date"].isna()]
    if len(missing):
        print(
            f"WARNING: {len(missing)} match(es) in matches_list have no date "
            f"after joining matches_stats_final on match_id. They cannot "
            f"contribute to any window flag. Expected: this should equal the "
            f"set in dropped_matches_log.csv (matches excluded during "
            f"stats collection). Per season:"
        )
        for season, grp in missing.groupby("season"):
            ids = sorted(int(m) for m in grp["match_id"])
            print(f"  {season}: {len(grp)} match(es) -> match_ids {ids}")

    return dated


def build_international_calendar() -> pd.DataFrame:
    windows = load_dataset("reference", "international_windows.csv")
    matches_list = load_dataset("processed", "matches_list.csv")
    match_stats = load_dataset("processed", "matches_stats_final.csv")

    dated = _attach_match_dates(matches_list, match_stats)

    # (season, round) -> list of kickoff dates (only matches that got a date).
    round_dates = (
        dated.dropna(subset=["match_date"])
        .groupby(["season", "round"])["match_date"]
        .apply(list)
        .to_dict()
    )

    # One row per (season, round) present in the fixture list, all flags 0.
    calendar = (
        matches_list[["season", "round"]]
        .drop_duplicates()
        .sort_values(["season", "round"])
        .reset_index(drop=True)
    )
    for col in FLAG_COLUMNS:
        calendar[col] = 0

    for _, window in windows.iterrows():
        wid = window["int_window_id"]
        season = window["season"]
        competition = window["competition"]

        col = COMPETITION_COLUMNS.get(competition)
        if col is None:
            print(
                f"WARNING: window {wid} has unrecognised competition "
                f"{competition!r}; no rounds flagged for it."
            )
            continue

        season_mask = calendar["season"] == season

        # --- 2023 Rugby World Cup: bypass the buffer, hardcode rounds 1-3 ---
        if col == "world_cup" and season == WORLD_CUP_2023_SEASON:
            mask = season_mask & calendar["round"].isin(WORLD_CUP_2023_ROUNDS)
            calendar.loc[mask, col] = 1
            print(
                f"{wid} ({competition}, {season}): hardcoded rounds "
                f"{sorted(WORLD_CUP_2023_ROUNDS)} flagged (2023 RWC exception, "
                f"no date buffer)."
            )
            continue

        start = pd.to_datetime(window["start_date"], errors="coerce")
        end = pd.to_datetime(window["end_date"], errors="coerce")
        if pd.isna(start) or pd.isna(end):
            print(
                f"WARNING: window {wid} ({competition}, {season}) has missing "
                f"start/end date; no rounds flagged for it."
            )
            continue

        lo = start - timedelta(days=PRE_BUFFER_DAYS)
        hi = end + timedelta(days=POST_BUFFER_DAYS)

        flagged = []
        for idx in calendar.index[season_mask]:
            rnd = calendar.at[idx, "round"]
            dates = round_dates.get((season, rnd), [])
            if any(lo <= d <= hi for d in dates):
                calendar.at[idx, col] = 1
                flagged.append(int(rnd))

        print(
            f"{wid} ({competition}, {season}): buffer "
            f"[{lo.date()} .. {hi.date()}] -> flagged rounds "
            f"{sorted(flagged) if flagged else '—'}"
        )

    calendar = calendar[["season", "round"] + FLAG_COLUMNS]
    save_to_csv(calendar, "international_calendar.csv", "processed")
    return calendar


if __name__ == "__main__":
    build_international_calendar()
