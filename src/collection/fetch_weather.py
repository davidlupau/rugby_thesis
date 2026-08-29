"""
Weather Data Collection for Rugby Matches

This module fetches historical weather data for Top 14 rugby matches using the
Open-Meteo API. It collects weather conditions at kickoff time for each match
based on venue coordinates.

Weather parameters collected:
    - Temperature (2m)
    - Humidity (2m)
    - Precipitation
    - Rain
    - Wind speed (10m)
    - Cloud cover
    - Day/night indicator

Workflow:
    1. Load match data and venue coordinates
    2. Merge match data with venue coordinates
    3. Fetch weather data for each match at kickoff time
    4. Save results to CSV file
"""

import requests
import pandas as pd
import sys
import time
from pathlib import Path
from typing import Union

# Add the src directory to the Python path
sys.path.append(str(Path(__file__).parent.parent))
from utils import load_dataset, save_to_csv
from constants import WEATHER_PARAM

HISTORICAL_API = "https://archive-api.open-meteo.com/v1/archive"


def merge_match_venue_data(df_matches: pd.DataFrame, df_venues: pd.DataFrame) -> pd.DataFrame:
    """
    Merge match data with venue coordinates.

    Performs a left join between match data and venue data based on stadium names.
    Handles cleaning and standardization of stadium names for better matching.

    Args:
        df_matches (pd.DataFrame): DataFrame containing match data with 'venue' column
        df_venues (pd.DataFrame): DataFrame containing venue data with 'stadium_name', 
                                  'latitude', and 'longitude' columns

    Returns:
        pd.DataFrame: Merged DataFrame with venue coordinates added to match data

    Note:
        Matches with unmatched venues will have NaN values for coordinate columns
        and will be skipped during weather data collection.
    """
    print("Merging match and venue data...")
    
    # Clean stadium names for better matching (strip whitespace, standardize)
    df_matches['venue_clean'] = df_matches['venue'].str.strip()
    df_venues['stadium_clean'] = df_venues['stadium_name'].str.strip()
    
    # Merge on stadium names
    df_merged = df_matches.merge(
        df_venues[['stadium_name', 'city', 'latitude', 'longitude']], 
        left_on='venue_clean', 
        right_on='stadium_name',
        how='left'
    )
    
    # Check for missing venue data
    missing_venues = df_merged['latitude'].isna().sum()
    if missing_venues > 0:
        print(f"Warning: {missing_venues} matches have missing venue coordinates")
        print("These matches will be skipped during weather collection")
        
        # Show which venues couldn't be matched (for debugging)
        unmatched = df_merged[df_merged['latitude'].isna()]['venue_clean'].unique()
        if len(unmatched) > 0 and len(unmatched) <= 10:
            print(f"   Unmatched venues: {', '.join(unmatched)}")
    
    # Check for successful matches
    matched_venues = len(df_merged) - missing_venues
    print(f"Successfully matched: {matched_venues}/{len(df_merged)} matches")
    print(f"Merged dataset ready: {len(df_merged)} matches\n")
    
    return df_merged

def fetch_weather_for_match(match_id: str, date: str, time: str, latitude: float, longitude: float) -> Union[dict, None]:
    """
    Fetch weather data for a single match at kickoff time.

    Uses the Open-Meteo API to retrieve historical weather data for the exact
    kickoff time of a match based on venue coordinates.

    Args:
        match_id (str/int): Match identifier for logging
        date (str): Match date in format YYYY-MM-DD
        time (str): Kickoff time in format HH:MM
        latitude (float): Venue latitude coordinate
        longitude (float): Venue longitude coordinate

    Returns:
        dict: Dictionary containing weather parameters, or None if request failed

    Weather Parameters Returned:
        - temperature: Temperature at 2m (Celsius)
        - humidity: Relative humidity at 2m (%)
        - precipitation: Precipitation amount (mm)
        - rain: Rain amount (mm)
        - wind_speed: Wind speed at 10m (km/h)
        - cloud_cover: Cloud cover (%)
        - is_day: Day/night indicator (1=day, 0=night)
    """
    try:
        # Parse kickoff hour
        kickoff_hour = int(time.split(':')[0])
        
        # Build API parameters
        params = {
            'latitude': latitude,
            'longitude': longitude,
            'start_date': date,
            'end_date': date,
            'hourly': ','.join(WEATHER_PARAM),
            'timezone': 'Europe/Paris'  # Top 14 is in France
        }
        
        # Make API request
        response = requests.get(HISTORICAL_API, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # Extract hourly data
        hourly = data.get('hourly', {})
        times = hourly.get('time', [])
        
        # Find closest hour to kickoff
        target_time = f"{date}T{kickoff_hour:02d}:00"
        
        if target_time not in times:
            print(f"Match {match_id}: Kickoff time {target_time} not found")
            return None
        
        idx = times.index(target_time)
        
        # Extract weather values
        weather_data = {
            'match_id': match_id,
            'temperature': hourly['temperature_2m'][idx],
            'humidity': hourly['relativehumidity_2m'][idx],
            'precipitation': hourly['precipitation'][idx],
            'rain': hourly['rain'][idx],
            'wind_speed': hourly['windspeed_10m'][idx],
            'cloud_cover': hourly['cloudcover'][idx],
            'is_day': hourly['is_day'][idx]
        }
        
        return weather_data
        
    except requests.exceptions.HTTPError as e:
        print(f"Match {match_id}: HTTP Error {response.status_code}")
        return None
    except requests.exceptions.Timeout:
        print(f"Match {match_id}: Request timeout")
        return None
    except Exception as e:
        print(f"Match {match_id}: {e}")
        return None

def collect_all_weather_data(df_merged: pd.DataFrame, delay: float = 0.5) -> pd.DataFrame:
    """
    Collect weather data for all matches.

    Iterates through all matches in the merged dataset and fetches weather data
    for each match at its kickoff time. Implements rate limiting to respect
    API usage policies.

    Args:
        df_merged (pd.DataFrame): Merged DataFrame containing match and venue data
        delay (float): Delay between API calls in seconds (default: 0.5)

    Returns:
        pd.DataFrame: DataFrame containing weather data for all successfully
                     processed matches

    Note:
        Matches with missing venue coordinates are skipped automatically.
        Progress is printed every 50 matches.
    """
    print(f"Collecting weather data for {len(df_merged)} matches...")
    print("=" * 80)
    
    weather_records = []
    success_count = 0
    failed_count = 0
    
    for idx, row in df_merged.iterrows():
        # Skip matches with missing coordinates
        if pd.isna(row['latitude']) or pd.isna(row['longitude']):
            print(f"Skipping match {row['match_id']} - missing coordinates")
            failed_count += 1
            continue
        
        # Fetch weather
        weather = fetch_weather_for_match(
            match_id=row['match_id'],
            date=row['date'],
            time=row['time'],
            latitude=row['latitude'],
            longitude=row['longitude']
        )
        
        if weather:
            weather_records.append(weather)
            success_count += 1
        else:
            failed_count += 1
        
        # Progress indicator every 50 matches
        if (idx + 1) % 50 == 0:
            print(f"Progress: {idx + 1}/{len(df_merged)} | {success_count} | {failed_count}")
        
        # Respect API rate limits
        time.sleep(delay)
    
    # Create DataFrame
    df_weather = pd.DataFrame(weather_records)
    
    print("=" * 80)
    print(f"Complete: {success_count} successful | {failed_count} failed")
    
    return df_weather

def fetch_weather_for_all_matches(delay: float = 0.5) -> pd.DataFrame:
    """
    Full pipeline: load matches + venues, merge in coordinates, fetch
    weather at kickoff time for every match, save to weather.csv.
    """
    # matches_stats_final.csv has match_date/match_time but not venue —
    # venue only lives in matches_list.csv, so join it in first.
    df_matches = load_dataset("processed", "matches_stats_final.csv")
    df_matches_list = load_dataset("processed", "matches_list.csv")
    df_matches = df_matches.merge(
        df_matches_list[["match_id", "venue"]], on="match_id", how="left"
    )
    df_matches = df_matches.rename(columns={"match_date": "date", "match_time": "time"})

    df_venues = load_dataset("reference", "venues.csv")

    df_merged = merge_match_venue_data(df_matches, df_venues)
    df_weather = collect_all_weather_data(df_merged, delay=delay)

    save_to_csv(df_weather, "weather.csv", "processed")
    return df_weather


if __name__ == "__main__":
    fetch_weather_for_all_matches()
