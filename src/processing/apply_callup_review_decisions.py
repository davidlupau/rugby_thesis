"""
Merge the manual review decisions from callup_review_queue.csv back into
callup_name_bridge.csv.

    decision == "y"  -> bridge row for that player_name gets
                        player_id    = candidate_player_id
                        match_method = "manual_review"
    decision == "n"  -> left unmatched (player_id stays null, match_method
                        stays "unmatched"); likely_cause is annotated so the
                        row reads as reviewed-and-rejected, not un-reviewed.
    blank / "?"      -> treated as unmatched for this merge, but logged so it
                        is not silently lost.

Idempotent: re-running changes nothing. Must be re-run after
build_callup_name_bridge.py, which rebuilds the bridge from scratch and has
no knowledge of the decisions.

ENCODING: callup_review_queue.csv is round-tripped through a spreadsheet
(Numbers / OnlyOffice), which adds a UTF-8 BOM to the header
("\\ufeffplayer_name") and, with Numbers, ";" delimiters. It is read here
with encoding="utf-8-sig" and a delimiter sniff, and the column names are
stripped. Any other CSV coming back from those tools needs the same check.
"""
import io
from pathlib import Path

import pandas as pd

from src.utils import load_dataset, save_to_csv

BRIDGE = "callup_name_bridge.csv"
QUEUE = "callup_review_queue.csv"
QUEUE_PATH = Path("data/processed") / QUEUE


def _read_reviewed_queue() -> pd.DataFrame:
    """Read the spreadsheet-edited queue: strip BOM, sniff , vs ; delimiter."""
    text = QUEUE_PATH.read_text(encoding="utf-8-sig")
    header = text.splitlines()[0]
    sep = ";" if header.count(";") > header.count(",") else ","
    q = pd.read_csv(io.StringIO(text), sep=sep)
    q.columns = [c.strip() for c in q.columns]
    q["decision"] = q["decision"].astype("string").str.strip().str.lower()
    return q


def apply_callup_review_decisions() -> pd.DataFrame:
    bridge = load_dataset("processed", BRIDGE)
    queue = _read_reviewed_queue()

    # ---- validate ----
    tokens = set(queue["decision"].dropna())
    bad = sorted(tokens - {"y", "n", "?", ""})
    if bad:
        raise ValueError(f"unexpected decision tokens in {QUEUE}: {bad}")

    blank = queue["decision"].isna() | queue["decision"].isin(["", "?"])
    if blank.any():
        print(f"WARNING: {int(blank.sum())} queue row(s) with blank/'?' decision "
              f"-> treated as unmatched:")
        for _, r in queue[blank].iterrows():
            print(f"  {r['player_name']!r} (candidate {r['candidate_player_id']})")

    y = queue[queue["decision"] == "y"]
    dup = y["player_name"].value_counts()
    dup = dup[dup > 1]
    if len(dup):
        raise ValueError(f"namesake violation - player_name(s) with >1 'y': {dict(dup)}")

    missing = set(queue["player_name"]) - set(bridge["player_name"])
    if missing:
        raise ValueError(f"{len(missing)} review name(s) absent from bridge: {sorted(missing)[:10]}")

    # ---- apply ----
    bridge = bridge.set_index("player_name")
    n_y = n_n = 0

    for _, r in y.iterrows():
        name, pid = r["player_name"], int(r["candidate_player_id"])
        if bridge.at[name, "match_method"] != "manual_review":
            n_y += 1  # counts only newly promoted rows -> 0 on a re-run
        bridge.at[name, "player_id"] = pid
        bridge.at[name, "match_method"] = "manual_review"
        bridge.at[name, "candidate_player_ids"] = str(pid)
        bridge.at[name, "likely_cause"] = ""

    rejected = set(queue["player_name"]) - set(y["player_name"])
    for name in rejected:
        if bridge.at[name, "match_method"] == "unmatched":
            was = str(bridge.at[name, "likely_cause"])
            if not was.startswith("manual review:"):
                bridge.at[name, "likely_cause"] = f"manual review: rejected (was: {was})"
                n_n += 1  # counts only rows actually annotated -> 0 on a re-run

    bridge = bridge.reset_index()

    # ---- report ----
    total_rows = int(bridge["callup_rows"].sum())
    n_names = len(bridge)
    n_rej_total = len(set(queue["player_name"]) - set(y["player_name"]))
    print("=" * 72)
    print(f"queue: {len(y)} 'y' / {n_rej_total} rejected names")
    print(f"this run: {n_y} newly promoted to manual_review, "
          f"{n_n} newly annotated reviewed-rejected (0/0 => already applied)")
    print("=" * 72)

    order = ["exact", "normalized", "normalized_extended", "manual_review",
             "manual_entry_profile_removed", "ambiguous", "unmatched"]
    present = [m for m in order if (bridge["match_method"] == m).any()]
    matched_methods = [m for m in present if m not in ("ambiguous", "unmatched")]

    print(f"{'match_method':<20}{'names':>7}{'name%':>8}{'callup_rows':>13}{'row%':>8}")
    for m in present:
        sub = bridge[bridge["match_method"] == m]
        rows = int(sub["callup_rows"].sum())
        print(f"{m:<20}{len(sub):>7}{len(sub) / n_names:>8.1%}{rows:>13}{rows / total_rows:>8.1%}")

    mm = bridge["match_method"].isin(matched_methods)
    tn, tr = int(mm.sum()), int(bridge.loc[mm, "callup_rows"].sum())
    un = bridge["match_method"] == "unmatched"
    ur = int(bridge.loc[un, "callup_rows"].sum())
    print("-" * 56)
    print(f"{'TOTAL MATCHED':<20}{tn:>7}{tn / n_names:>8.1%}{tr:>13}{tr / total_rows:>8.1%}")
    print(f"{'unmatched':<20}{int(un.sum()):>7}{int(un.sum()) / n_names:>8.1%}{ur:>13}{ur / total_rows:>8.1%}")

    save_to_csv(bridge[["player_name", "player_id", "match_method",
                        "candidate_player_ids", "likely_cause", "callup_rows"]],
                BRIDGE, "processed")
    return bridge


if __name__ == "__main__":
    apply_callup_review_decisions()
