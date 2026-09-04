"""
Export data/processed/callup_review_queue.csv — a flat, eyeball-friendly view
of the manual-review rows in callup_name_bridge.csv (the surname-match tiers:
"surname match, forename differs" and "surname match, multiple namesakes").

One row per (call-up name x candidate player_id), so a namesake case with two
candidates produces two rows. For each candidate we pull full_name, every
club it appears against in players.csv (with the seasons), and nationality,
so the reviewer can judge club / nationality plausibility rather than staring
at names alone. The call-up side carries the windows / competitions the name
was called up in, for the same reason.

Rows are sorted by n_callup_rows descending, so the names that appear in the
most call-up rows (highest downstream impact if mismatched) come first.

`decision` column — filled in by the reviewer, not by this script:
    y            confirmed match: adopt candidate_player_id for this call-up name
    n            confirmed NOT a match: leave the call-up name unmatched
    blank / ?    unresolved: treated as unmatched by default, revisit later;
                 does NOT block downstream use of the bridge
See data/processed/callup_review_queue_README.md for the same note.

The reviewed file is merged back by apply_callup_review_decisions.py.

ENCODING WARNING: this file gets opened and re-saved in a spreadsheet
(Numbers, OnlyOffice). Those exports mangle CSVs — OnlyOffice prepends a
UTF-8 BOM to the header ("\\ufeffplayer_name"), Numbers switches to ";"
delimiters and CRLF. Anything reading a spreadsheet-round-tripped CSV in
this project must use encoding="utf-8-sig", sniff the delimiter, and strip
the header cells (apply_callup_review_decisions.py does all three).

Reads callup_name_bridge.csv (so run build_callup_name_bridge.py first).
Does not feed the pipeline — this is a review aid.
"""
import pandas as pd

from src.utils import load_dataset, save_to_csv

REVIEW_CAUSES = (
    "surname match, forename differs (single candidate; nickname/initial/spelling)",
    "surname match, multiple namesakes",
)


def export_callup_review_queue() -> pd.DataFrame:
    bridge = load_dataset("processed", "callup_name_bridge.csv")
    callups = load_dataset("processed", "player_callups.csv")
    players = load_dataset("processed", "players.csv")

    team_cols = [c for c in players.columns if c.endswith("_team")]

    def clubs_for(pid: int) -> str:
        row = players.loc[players["player_id"] == pid]
        if row.empty:
            return ""
        row = row.iloc[0]
        parts = []
        for c in team_cols:
            if pd.notna(row[c]):
                parts.append(f"{row[c]} ({c.replace('_team', '')})")
        return "; ".join(parts) if parts else "(no Top 14 club in players.csv)"

    pinfo = players.set_index("player_id")

    # call-up side: windows / seasons / competitions per name
    grp = callups.groupby("player_name").agg(
        int_window_ids=("int_window_id", lambda s: ";".join(sorted(s.unique()))),
        seasons=("season", lambda s: ";".join(sorted(s.unique()))),
        competitions=("competition", lambda s: ";".join(sorted(s.unique()))),
        n_callup_rows=("int_window_id", "size"),
    )

    queue = bridge[bridge["likely_cause"].isin(REVIEW_CAUSES)].copy()

    out_rows = []
    for _, r in queue.iterrows():
        name = r["player_name"]
        cands = [int(x) for x in str(r["candidate_player_ids"]).split(";") if x]
        g = grp.loc[name]
        for pid in cands:
            out_rows.append({
                "player_name": name,
                "int_window_ids": g["int_window_ids"],
                "seasons": g["seasons"],
                "competitions": g["competitions"],
                "n_callup_rows": int(g["n_callup_rows"]),
                "likely_cause": r["likely_cause"],
                "n_candidates": len(cands),
                "candidate_player_id": pid,
                "candidate_full_name": pinfo.at[pid, "full_name"] if pid in pinfo.index else "",
                "candidate_nationality": pinfo.at[pid, "nationality"] if pid in pinfo.index else "",
                "candidate_clubs": clubs_for(pid),
                "decision": "",   # reviewer fills: y / n / ?
            })

    # highest-impact names first; keep a name's candidate rows adjacent
    review = pd.DataFrame(out_rows).sort_values(
        ["n_callup_rows", "player_name", "candidate_player_id"],
        ascending=[False, True, True],
    ).reset_index(drop=True)

    print(f"review-queue names: {queue['player_name'].nunique()}  "
          f"-> candidate rows: {len(review)}")
    print(review["likely_cause"].value_counts().to_string())

    save_to_csv(review, "callup_review_queue.csv", "processed")
    return review


if __name__ == "__main__":
    export_callup_review_queue()
