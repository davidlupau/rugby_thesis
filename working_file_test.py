"""
Fetch weather data (Open-Meteo) for every match in matches_stats_final.csv.
Produces data/processed/weather.csv.
"""
from src.collection.fetch_weather import fetch_weather_for_all_matches

df_weather = fetch_weather_for_all_matches(delay=0.3)
print(f"\nDone: {len(df_weather)} weather records saved to data/processed/weather.csv")
