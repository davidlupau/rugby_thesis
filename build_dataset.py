import pandas as pd

def main():
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

if __name__ == "__main__":
    main()