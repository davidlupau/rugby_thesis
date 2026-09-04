"""
Build data/processed/callup_name_bridge.csv — a name -> player_id bridge
between:
    player_callups.csv   keyed by player_name (Wikipedia spelling)
    players.csv          keyed by player_id, with full_name (LNR spelling)

player_callups.csv lists the FULL national squads of every nation in each
international window (up to 20 nations at RWC 2023). Most of those players
have never been contracted to a Top 14 club, so a low overall match rate is
expected and correct — the ones that matter are the Top 14 players among the
call-ups, and those match well (all France regulars, plus the Georgian /
Fijian / Argentine / Pacific imports in the league).

Three tiers are auto-matched, all safe:
    exact                player_name == full_name
    normalized           case-fold + accent-strip + de-punct, and the
                         normalized form maps to exactly ONE player_id.
                         Includes an apostrophe/hyphen-deleted fallback
                         (_norm_tight) for Polynesian names Wikipedia and LNR
                         spell differently, e.g. "Michael Alaalatoa" ->
                         "Michael Ala'alatoa", "Leicester Fainga'anuku" ->
                         "Leicester Faingaanuku" -- unique-hit only.
    normalized_extended  first token + last token match exactly ONE player,
                         middle name(s) differ only. LNR stores full legal
                         names (middle names included), Wikipedia the common
                         name, e.g. "Siya Kolisi" -> "Siyamthanda Kolisi",
                         "Jiuta Wainiqolo" -> "Jiuta Naqoli Wainiqolo".

Same-player / two-rows is EXPECTED, not a duplicate-match bug: the bridge
grain is unique call-up name, not unique player, and Wikipedia lists some
players under two spellings (accent present/absent, apostrophe present/
absent). So one player_id can legitimately be reached from two rows --
"Julian Montoya" / "Julián Montoya" -> 13598, "Grégory Alldritt" /
"Gregory Alldritt" -> 980, "Alexander Kuntelia" / "Alexsandre Kuntelia" ->
935 (this last pair via the manual-review merge). ~9 player_ids are hit by
two call-up names each.

Everything else is left unmatched (player_id null) with:
    likely_cause            best guess at why it did not match
    candidate_player_ids    concrete player_id(s) for manual review, when the
                            surname (or first+last) overlaps players.csv

Nothing fuzzy or ambiguous is auto-resolved — the surname-overlap candidates
in particular are mostly common-surname false positives (every "_ Smith" ->
the single Smith in players.csv) and need a human. Those candidates are
exported by export_callup_review_queue.py, reviewed by hand, and merged back
by apply_callup_review_decisions.py (which adds the "manual_review" tier and
annotates rejected rows). Re-running THIS script rebuilds the bridge from
scratch and drops those manual results, so apply_callup_review_decisions.py
must be re-run afterwards.

MANUAL TIER — "manual_entry_profile_removed"
-------------------------------------------
Two call-ups are matched to a player_id by hand, NOT through any tier above
and NOT through players.csv, because their LNR profile page has been taken
down (the /joueur/<id>-<slug> path 302-redirects to /joueurs on both
prod2.lnr.fr and top14.lnr.fr — a permanent removal, confirmed 2026-09, not
a scraper timeout). With no profile page there is no players.csv row to
match against, so the normal name -> full_name matching cannot reach them.

    Lopeti Timani      -> 11434   (RC Toulon)
    Sonatane Takulua   -> 86      (RC Toulon)

Both are safe to assert directly: their Top 14 appearances are in
player_minutes.csv (keyed by player_id, sourced from match rosters, not from
the profile page) and their international call-ups are in player_callups.csv.
No players.csv data is needed for them downstream — the absence calculation
reads player_minutes.csv directly, and neither player has a prior season that
would require the players.csv-sourced minutes-shrinkage baseline.

Like the manual_review tier, these two rows are NOT reproduced by re-running
this script (it rebuilds from player_callups.csv + players.csv only) — they
must be re-applied by hand, or via apply_callup_review_decisions.py if they
are added to the review queue.

The other 27 players in players_incomplete.csv have the same 302-removed
profile pages but are left permanently unresolved: none is a confirmed
international call-up whose absence feature depends on them, so a manual
player_id assertion is not worth the risk.

Output grain: one row per unique player_name in player_callups.csv.
This script does NOT modify player_callups.csv.
"""
import re
import unicodedata

import pandas as pd

from src.utils import load_dataset, save_to_csv


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s)
                   if not unicodedata.combining(c))


def _norm(s: str) -> str:
    """case-fold + accent-strip + de-punctuate + collapse whitespace."""
    s = _strip_accents(str(s)).casefold()
    s = re.sub(r"[^\w\s]", " ",
               s.replace("-", " ").replace("'", " ").replace("’", " "))
    return re.sub(r"\s+", " ", s).strip()


def _norm_tight(s: str) -> str:
    """Like _norm but DELETES apostrophes/hyphens instead of splitting on them.

    Wikipedia and LNR disagree about the apostrophe in Polynesian names
    ("Michael Alaalatoa" vs "Michael Ala'alatoa", "Leicester Fainga'anuku" vs
    "Leicester Faingaanuku"). Splitting on the apostrophe changes the token
    count and breaks the surname match; deleting it makes both spellings the
    same string. Used only as a unique-hit fallback, so it cannot add
    ambiguity.
    """
    s = _strip_accents(str(s)).casefold().replace("-", "").replace("'", "").replace("’", "")
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def build_callup_name_bridge() -> pd.DataFrame:
    callups = load_dataset("processed", "player_callups.csv")
    players = load_dataset("processed", "players.csv")

    names = sorted(callups["player_name"].dropna().unique())
    row_counts = callups["player_name"].value_counts()
    total_rows = int(row_counts.sum())
    n_unique = len(names)

    exact_lut = dict(zip(players["full_name"], players["player_id"]))
    by_id = players.set_index("player_id")

    # normalized full-name -> [ids]; (first, last) -> [ids]; last -> [ids]
    norm_lut: dict[str, list[int]] = {}
    tight_lut: dict[str, list[int]] = {}
    firstlast_lut: dict[tuple[str, str], list[int]] = {}
    last_lut: dict[str, list[int]] = {}
    for _, r in players.iterrows():
        pid = int(r["player_id"])
        toks = _norm(r["full_name"]).split()
        norm_lut.setdefault(" ".join(toks), []).append(pid)
        tight_lut.setdefault(_norm_tight(r["full_name"]), []).append(pid)
        if len(toks) >= 2:
            firstlast_lut.setdefault((toks[0], toks[-1]), []).append(pid)
            last_lut.setdefault(toks[-1], []).append(pid)

    records = []
    for nm in names:
        rec = {
            "player_name": nm,
            "player_id": pd.NA,
            "match_method": "unmatched",
            "candidate_player_ids": "",
            "likely_cause": "",
            "callup_rows": int(row_counts.get(nm, 0)),
        }
        toks = _norm(nm).split()
        key = " ".join(toks)
        norm_cands = norm_lut.get(key, [])

        tight_cands = tight_lut.get(_norm_tight(nm), [])

        if nm in exact_lut:
            rec.update(player_id=int(exact_lut[nm]), match_method="exact")
        elif len(norm_cands) == 1:
            rec.update(player_id=norm_cands[0], match_method="normalized")
        elif len(norm_cands) > 1:
            rec.update(match_method="ambiguous",
                       candidate_player_ids=";".join(map(str, norm_cands)),
                       likely_cause="normalized name maps to >=2 player_ids")
        elif len(tight_cands) == 1:
            # apostrophe/hyphen spelling difference only (Polynesian names)
            rec.update(player_id=tight_cands[0], match_method="normalized")
        else:
            fl = firstlast_lut.get((toks[0], toks[-1]), []) if len(toks) >= 2 else []
            ln = last_lut.get(toks[-1], []) if toks else []
            if len(fl) == 1:
                # first+last match a single player, middle name(s) differ only.
                rec.update(player_id=fl[0], match_method="normalized_extended")
            elif len(fl) > 1:
                rec["likely_cause"] = "first+last match, multiple candidates"
                rec["candidate_player_ids"] = ";".join(map(str, fl))
            elif len(ln) == 1:
                rec["likely_cause"] = "surname match, forename differs (single candidate; nickname/initial/spelling)"
                rec["candidate_player_ids"] = str(ln[0])
            elif len(ln) > 1:
                rec["likely_cause"] = "surname match, multiple namesakes"
                rec["candidate_player_ids"] = ";".join(map(str, ln))
            else:
                rec["likely_cause"] = "no surname overlap in players.csv (likely never contracted to a Top 14 club)"
        records.append(rec)

    bridge = pd.DataFrame.from_records(records)
    m = bridge["match_method"]

    def rc(mask: pd.Series) -> int:
        return int(bridge.loc[mask, "callup_rows"].sum())

    n_exact = int((m == "exact").sum())
    n_norm = int((m == "normalized").sum())
    n_ext = int((m == "normalized_extended").sum())
    n_amb = int((m == "ambiguous").sum())
    n_un = int((m == "unmatched").sum())
    matched_methods = ["exact", "normalized", "normalized_extended"]
    cum = n_exact + n_norm + n_ext

    print("=" * 72)
    print(f"unique call-up names: {n_unique}      call-up rows: {total_rows}")
    print("=" * 72)
    print(f"(1) exact vs full_name        : {n_exact:4d}/{n_unique} ({n_exact / n_unique:5.1%})"
          f"  | rows {rc(m == 'exact'):4d}/{total_rows} ({rc(m == 'exact') / total_rows:.1%})")
    print(f"(2) + normalized (unique)     : {n_norm:4d} new"
          f"  | rows {rc(m.isin(['exact', 'normalized'])):4d}/{total_rows}")
    print(f"(3) + normalized_extended     : {n_ext:4d} new (first+last unique, middle names differ)"
          f"  -> {cum}/{n_unique} ({cum / n_unique:5.1%})"
          f"  | rows {rc(m.isin(matched_methods)):4d}/{total_rows} "
          f"({rc(m.isin(matched_methods)) / total_rows:.1%})")
    print(f"    ambiguous (not matched)   : {n_amb:4d}")
    print(f"    unmatched                 : {n_un:4d} ({n_un / n_unique:5.1%})")
    print("\n(3) unmatched / ambiguous by likely cause  [names | call-up rows]:")
    for cause, g in bridge[m.isin(["unmatched", "ambiguous"])].groupby("likely_cause"):
        print(f"  [{len(g):4d} | {int(g['callup_rows'].sum()):4d}]  {cause}")

    save_to_csv(
        bridge[["player_name", "player_id", "match_method",
                "candidate_player_ids", "likely_cause", "callup_rows"]],
        "callup_name_bridge.csv", "processed",
    )
    return bridge


if __name__ == "__main__":
    build_callup_name_bridge()
