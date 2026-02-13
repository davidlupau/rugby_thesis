

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
    "2017-2018",
    "2018-2019", 
    "2021-2022",
    "2022-2023",
    "2023-2024",
    "2024-2025"
]