"""
Build data/processed/european_congestion.csv: a per-match, per-team flag for
whether that team had a European Cup (Champions Cup / Challenge Cup)
fixture within +/-7 days of a Top 14 match -- a contextual "not at full
strength" feature alongside the player-importance-weighted international
absence coefficient (calculate_players_away.py).

Sources (joined here):
    data/reference/european_cup_dates.csv
        season, id, date -- one row per European matchday. 2021-2022 has 9
        rows (21_22_R1..21_22_R9) because that season uniquely used a
        two-legged Round of 16 (EPCR reverted to single-leg from 2022-23
        onward); every other season has 8. The row count per season is read
        from whatever is actually present -- never hardcoded.
    data/reference/european_cup_teams.csv
        team_name, <one 0/1 column per matchday id> -- did that team play a
        European fixture that matchday. Includes teams that were never
        actually in Top 14 during 2021-22..2025-26 (e.g. SU Agen) and teams
        that were in Top 14 but never qualified for Europe (e.g. FC
        Grenoble Rugby, Provence Rugby, Stade Montois) -- both cases are
        legitimate all-zero rows, not gaps, and must resolve to congestion
        0, not an error.
    data/processed/matches_list.csv
        match_id, season, round, home_team, away_team.
    data/processed/matches_stats_final.csv
        match_id, match_date -- supplies the date for each match, same
        source fetch_weather.py and build_international_calendar.py already
        use. Matches with no date after this join (the same ~70-match gap
        documented in build_international_calendar.py, from
        dropped_matches_log.csv) cannot get a congestion flag and are left
        at 0 on both sides, with a warning, rather than failing.

MATCHDAY ID MISMATCH (discovered building this, not assumed): the two
reference files disagree on the separator for the 2021-2022 matchday ids.
european_cup_dates.csv uses "21_22_R1".."21_22_R9" (underscore); the column
headers in european_cup_teams.csv use "21_22-R1".."21_22-R9" (hyphen) for
that same season only -- every other season (22_23_R1 onward) already
matches exactly between the two files. A literal string join would
silently drop all nine 2021-2022 matchdays. _normalize_matchday_id() below
collapses both spellings to one canonical form ("21_22_R1", ...) before
joining, so this is transparent to the rest of the script.

TEAM-NAME WHITESPACE (also discovered here): matches_list.csv has
"Montpellier Hérault Rugby " (trailing space) on 5 playoff rows (round
28/29/30, seasons 2021-2022, 2023-2024, 2025-2026), which does not match
the clean "Montpellier Hérault Rugby" in european_cup_teams.csv. Team names
are stripped on BOTH sides before joining -- not just on
european_cup_teams.csv as originally scoped, since matches_list.csv turned
out to have the same class of issue.

Logic
-----
For each Top 14 match (regular season + playoffs, no filtering by round
type -- pool stage and knockout both count):
    1. Look up its date via the matches_stats_final.csv join.
    2. For the home team and, separately, the away team: does that team
       have a 1 in european_cup_teams.csv for any matchday in the SAME
       season (by season label, never crossing season boundaries) whose
       date falls within [match_date - 7 days, match_date + 7 days]?
    3. home_euro_congestion / away_euro_congestion = 1 if yes, else 0.

Team-level, not round-level (unlike build_international_calendar.py's
round-level flags): the same round can have one team's opponent congested
and the other not, so every match gets two independent flags.

Output grain: one row per match_id in matches_list.csv (every match, not
just ones with a European fixture nearby -- those simply get 0 on the
relevant side).
"""
import re

import pandas as pd

from src.utils import load_dataset, save_to_csv

CONGESTION_WINDOW_DAYS = 7


def _normalize_matchday_id(raw: str) -> str:
    """
    '21_22-R5' and '21_22_R5' (and anything with stray whitespace) all
    collapse to '21_22_R5'. See MATCHDAY ID MISMATCH note in the module
    docstring -- the two source files disagree on the separator for the
    2021-2022 season only, everything else already matches.
    """
    s = str(raw).strip()
    m = re.match(r"^(\d{2}_\d{2})[-_]R(\d+)$", s)
    if not m:
        return s
    season_code, round_num = m.groups()
    return f"{season_code}_R{round_num}"


def _load_european_dates() -> pd.DataFrame:
    dates = load_dataset("reference", "european_cup_dates.csv")
    dates["season"] = dates["season"].astype(str).str.strip()
    dates["id_norm"] = dates["id"].apply(_normalize_matchday_id)
    dates["date"] = pd.to_datetime(dates["date"], errors="coerce")

    bad = dates[dates["date"].isna()]
    if len(bad):
        print(f"WARNING: {len(bad)} european_cup_dates.csv row(s) have an "
              f"unparseable date and will never flag congestion: "
              f"{bad['id'].tolist()}")

    counts = dates.groupby("season").size()
    print("european_cup_dates.csv matchdays per season (read as-is, not "
          f"hardcoded):\n{counts.to_string()}")
    return dates


def _load_european_teams() -> pd.DataFrame:
    teams = load_dataset("reference", "european_cup_teams.csv")
    teams.columns = [c.strip() for c in teams.columns]
    teams["team_name"] = teams["team_name"].astype(str).str.strip()

    matchday_cols = [c for c in teams.columns if c != "team_name"]
    rename_map = {c: _normalize_matchday_id(c) for c in matchday_cols}
    teams = teams.rename(columns=rename_map)
    return teams


def _build_team_season_matchday_dates(
    dates: pd.DataFrame, teams: pd.DataFrame
) -> dict:
    """
    (team_name, season) -> sorted list of Timestamps for every matchday
    that team played (teams.csv value == 1), restricted to matchdays whose
    id_norm actually exists in european_cup_dates.csv for that season.
    """
    id_to_date = dict(zip(dates["id_norm"], dates["date"]))
    id_to_season = dict(zip(dates["id_norm"], dates["season"]))

    matchday_cols = [c for c in teams.columns if c != "team_name"]
    missing_dates = sorted(set(matchday_cols) - set(id_to_date))
    if missing_dates:
        print(f"WARNING: {len(missing_dates)} european_cup_teams.csv "
              f"matchday column(s) have no matching row in "
              f"european_cup_dates.csv even after id normalization -- "
              f"these can never flag congestion: {missing_dates}")

    lookup: dict = {}
    for _, row in teams.iterrows():
        team = row["team_name"]
        for col in matchday_cols:
            if col not in id_to_date:
                continue
            played = row[col]
            if pd.isna(played) or int(played) != 1:
                continue
            season = id_to_season[col]
            lookup.setdefault((team, season), []).append(id_to_date[col])

    for key in lookup:
        lookup[key].sort()
    return lookup


def _attach_match_dates(matches: pd.DataFrame) -> pd.DataFrame:
    stats = load_dataset("processed", "matches_stats_final.csv")
    dated = matches.merge(stats[["match_id", "match_date"]], on="match_id", how="left")
    dated["match_date"] = pd.to_datetime(dated["match_date"], errors="coerce")

    missing = dated[dated["match_date"].isna()]
    if len(missing):
        print(f"WARNING: {len(missing)} match(es) in matches_list have no date "
              f"after joining matches_stats_final on match_id -- they cannot "
              f"get a congestion flag (expected to match the "
              f"dropped_matches_log.csv gap; see build_international_calendar.py).")
    return dated


def _is_congested(team: str, season: str, match_date, lookup: dict) -> int:
    if pd.isna(match_date):
        return 0
    candidate_dates = lookup.get((team, season))
    if not candidate_dates:
        return 0
    window = pd.Timedelta(days=CONGESTION_WINDOW_DAYS)
    lo, hi = match_date - window, match_date + window
    return int(any(lo <= d <= hi for d in candidate_dates))


def calculate_european_congestion() -> pd.DataFrame:
    matches = load_dataset("processed", "matches_list.csv")
    matches = matches.copy()
    matches["home_team"] = matches["home_team"].astype(str).str.strip()
    matches["away_team"] = matches["away_team"].astype(str).str.strip()

    dates = _load_european_dates()
    teams = _load_european_teams()
    lookup = _build_team_season_matchday_dates(dates, teams)

    dated_matches = _attach_match_dates(matches)

    results = []
    for _, m in dated_matches.iterrows():
        season = m["season"]
        home_flag = _is_congested(m["home_team"], season, m["match_date"], lookup)
        away_flag = _is_congested(m["away_team"], season, m["match_date"], lookup)
        results.append({
            "match_id": m["match_id"],
            "season": season,
            "round": m["round"],
            "is_playoff": m["is_playoff"],
            "home_team": m["home_team"],
            "away_team": m["away_team"],
            "home_euro_congestion": home_flag,
            "away_euro_congestion": away_flag,
        })

    out = pd.DataFrame(results)

    n_home = int(out["home_euro_congestion"].sum())
    n_away = int(out["away_euro_congestion"].sum())
    print("=" * 72)
    print(f"matches: {len(out)}  |  home_euro_congestion=1: {n_home}  |  "
          f"away_euro_congestion=1: {n_away}")
    playoff_flagged = out[(out["is_playoff"] == 1) &
                          ((out["home_euro_congestion"] == 1) |
                           (out["away_euro_congestion"] == 1))]
    print(f"playoff matches (is_playoff==1) with any flag=1: {len(playoff_flagged)}")
    if len(playoff_flagged):
        print(playoff_flagged[["match_id", "season", "round", "home_team",
                                "away_team", "home_euro_congestion",
                                "away_euro_congestion"]].to_string())
    print("=" * 72)

    save_to_csv(
        out[["match_id", "season", "round", "home_team", "away_team",
             "home_euro_congestion", "away_euro_congestion"]],
        "european_congestion.csv", "processed",
    )
    return out


if __name__ == "__main__":
    calculate_european_congestion()
