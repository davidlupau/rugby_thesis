import requests
import pandas as pd
import sys
import time
from pathlib import Path

# Add the src directory to the Python path
sys.path.append(str(Path(__file__).parent.parent))
from utils import load_dataset, save_to_csv
from constants import WEATHER_PARAM


def merge_match_venue_data(df_matches, df_venues):
    """
    Merge match data with venue coordinates
    
    The merge is done on stadium_name, which should be present in both:
    - matches.csv: 'venue' column contains stadium names from LNR
    - venues.csv: 'stadium_name' column contains the reference names
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

def fetch_weather_for_match(match_id, date, time, latitude, longitude):
    """
    Fetch weather data for a single match at kickoff time
    
    Parameters:
    -----------
    match_id : str/int - Match identifier
    date : str - Match date (YYYY-MM-DD)
    time : str - Kickoff time (HH:MM)
    latitude : float - Venue latitude
    longitude : float - Venue longitude
    
    Returns:
    --------
    dict : Weather data or None if failed
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
        response = requests.get(historical_api, params=params, timeout=10)
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

def collect_all_weather_data(df_merged, delay=0.5):
    """
    Collect weather data for all matches
    
    Parameters:
    -----------
    df_merged : DataFrame - Merged match and venue data
    delay : float - Delay between API calls (seconds)
    
    Returns:
    --------
    DataFrame : Weather data for all matches
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

if __name__ == "__main__":
    # load list of matches and venues
    df_matches = load_dataset("processed", "matches.csv")
    df_venues = load_dataset("processed", "venues.csv")
    
    # Open-Meteo API configuration
    historical_api = "https://archive-api.open-meteo.com/v1/archive"
    
    # Merge matches with venue coordinates
    df_merged = merge_match_venue_data(df_matches, df_venues)

    # Collect weather data
    df_weather = collect_all_weather_data(df_merged, delay=0.5)
    
    # Create a csv file
    save_to_csv(df_weather, "weather.csv", "processed")
