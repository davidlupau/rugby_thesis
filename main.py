from data_processing import load_dataset, save_analysis_to_csv

if __name__ == "__main__":

    # Retrieving matches list
    print("\n")
    print("Retrieving list of matches \n")
    df_matches = load_dataset("processed", "matches.csv")
    print("List successfully retrieved")
    
    # Retrieving weather data
    print("\n")
    print("Retrieving weather data \n")
    print("Data successfully retrieved")
    save_analysis_to_csv(df_matches, "1. matches_weather.csv")

  