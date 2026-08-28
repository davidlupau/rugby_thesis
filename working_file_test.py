"""
Quick targeted test: re-scrape just match 67 (known real stats) and match
11057 (known genuinely empty) to sanity-check the verified_empty detection
fix in scrape_lnr.py, without running the full retry_incomplete_matches()
pass over all 64 confirmed_no_data matches.
"""
from src.utils import load_dataset
from src.collection.scrape_lnr import scrape_lnr

TEST_MATCH_IDS = [67, 11057]

matches_list = load_dataset("processed", "matches_list.csv")
test_matches = matches_list[matches_list["match_id"].isin(TEST_MATCH_IDS)].copy()

print(f"Scraping {len(test_matches)} test matches: {TEST_MATCH_IDS}")
stats_df = scrape_lnr(test_matches, output_csv="test_two_matches.csv")

print("\n" + "=" * 70)
print("RESULTS")
print("=" * 70)
fields_of_interest = [
    "match_id", "home_score", "away_score",
    "home_scrums_played", "away_scrums_played",
    "home_passes", "away_passes",
]
for mid in TEST_MATCH_IDS:
    row = stats_df[stats_df["match_id"] == mid]
    if row.empty:
        print(f"match {mid}: no row returned (hard failure/exception)")
        continue
    row = row.iloc[0]
    populated = row.notna().sum()
    print(f"match {mid}: {populated} fields populated")
    for f in fields_of_interest:
        print(f"    {f}: {row.get(f)}")

incomplete = load_dataset("processed", "test_two_matches_incomplete.csv")
print("\nIncomplete-tracking result for this test run:")
print(incomplete.to_string() if incomplete is not None else "  (none — both matches came back complete)")
