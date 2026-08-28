

# List of weather variables
WEATHER_PARAM = [
    "temperature_2m",           # Temperature at 2 meters (°C)
    "relativehumidity_2m",      # Relative humidity (%)
    "precipitation",            # Precipitation (mm)
    "rain",                     # Rain only (mm)
    "windspeed_10m",           # Wind speed at 10m (km/h)
    "cloudcover",              # Cloud cover (%)
    "is_day"                 # Is day or night
]

# Scraping configuration
SCRAPING_CONFIG = {
    'rate_limit_seconds': 2,  # Wait 2 seconds between requests (be respectful!)
    'max_retries': 3,
    'timeout': 10,
    'user_agent': 'UniversityResearchBot/1.0 (BSc Thesis Project; your.email@domain.com)'
}

# List of seasons
SEASONS = [
    "2021-2022",
    "2022-2023",
    "2023-2024",
    "2024-2025",
    "2025-2026"
]

# Translations of terms from LNR website
TRANSLATIONS = {
}

# Match_ids individually verified (by a human, against the live site) to
# have no stats published at all. This is NOT inferred from season/round
# proximity — a match sitting inside a range where other matches are dead
# is not evidence about that specific match. Some 2022-2023 R10-R18 matches
# (e.g. 67, 69, 70) were previously mislabeled this way and turned out to
# have complete stats; they were just failing on scraper timeouts.
CONFIRMED_DEAD_MATCH_IDS = {9922, 11057, 11795, 11796, 11797, 11798, 11800}


def is_confirmed_dead(match_id) -> bool:
    """
    True only for match_ids individually pre-verified as having no stats.

    This is a legacy/backfill check for incomplete-tracking rows saved
    before scrape_lnr.py could detect "verified empty" directly from a
    live page load (see NO_STATS_TEXT in scrape_lnr.py). It must never be
    used to infer status from season, round, or any other match's outcome —
    only from an individual match's own verified result.
    """
    try:
        return int(match_id) in CONFIRMED_DEAD_MATCH_IDS
    except (TypeError, ValueError):
        return False