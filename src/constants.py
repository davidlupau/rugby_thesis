

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

# Matches verified against the live LNR site to have no stats published at all
# (as opposed to a scraper timeout that might succeed on retry).
CONFIRMED_DEAD_MATCH_IDS = {9922, 11057, 11795, 11796, 11797, 11798, 11800}


def is_confirmed_dead(match_id, season, round_num) -> bool:
    """
    True if a match is known to have no stats on the live site and should
    not be retried after a scraper timeout/incomplete result.

    Covers two cases:
      - explicit match_ids verified individually (CONFIRMED_DEAD_MATCH_IDS)
      - 2022-2023 rounds 10-18, a block with no published stats
    """
    try:
        if int(match_id) in CONFIRMED_DEAD_MATCH_IDS:
            return True
    except (TypeError, ValueError):
        pass

    try:
        if str(season) == "2022-2023" and 10 <= int(round_num) <= 18:
            return True
    except (TypeError, ValueError):
        pass

    return False