#!/usr/bin/env python3
"""
Script to scrape match information from LNR Top 14 website.
This script extracts match details for all rounds of regular season (1-26) for all seasons
listed in the seasons.csv file and combines them with playoff matches from playoffs.csv.
"""

import requests
from bs4 import BeautifulSoup
import pandas as pd
import re
import time
import sys
from pathlib import Path

# Add the src directory to the path so we can import constants and utils
sys.path.append(str(Path(__file__).parent.parent))
from constants import SEASONS, SCRAPING_CONFIG
from utils import load_dataset, save_to_csv


def get_project_root():
    """
    Get the project root directory path.
    
    Returns:
        Path: The project root directory
    """
    # Go up two levels from src/collection/ to get to project root
    return Path(__file__).parent.parent.parent





def get_project_root():
    """
    Get the project root directory path.
    
    Returns:
        Path: The project root directory
    """
    # Go up two levels from src/collection/ to get to project root
    return Path(__file__).parent.parent.parent


def get_team_venue(team_name, teams_df):
    """
    Get the venue for a given team name from the teams DataFrame.
    
    Args:
        team_name (str): Name of the team
        teams_df (pd.DataFrame): DataFrame containing team information
        
    Returns:
        str: Venue name or 'Unknown' if not found
    """
    # Clean team name by removing common suffixes
    clean_name = team_name.lower()
    
    # Try to find the team in the DataFrame
    for index, row in teams_df.iterrows():
        if clean_name in row['team_name'].lower():
            return row['venue']
    
    return 'Unknown'


def load_playoff_matches():
    """
    Load playoff matches from the playoffs.csv file.
    
    Returns:
        list: List of dictionaries containing playoff match information
    """
    try:
        playoffs_df = load_dataset('processed', 'playoffs.csv')
        
        if playoffs_df is None:
            return []
        
        # Rename 'match_url' column to 'url' for consistency
        if 'match_url' in playoffs_df.columns:
            playoffs_df = playoffs_df.rename(columns={'match_url': 'url'})
        
        playoff_matches = []
        for index, row in playoffs_df.iterrows():
            playoff_matches.append({
                'match_id': row['match_id'],
                'season': row['season'],
                'round': row['round'],
                'venue': row['venue'],
                'home_team': row['home_team'],
                'away_team': row['away_team'],
                'url': row['url'],
                'is_playoff': 1  # 1 = playoff/access match
            })
        
        return playoff_matches
        
    except Exception as e:
        print(f"Error loading playoff matches: {e}")
        return []


def scrape_matches_for_round(season, round_num):
    """
    Scrape match information for a specific season and round.
    
    Args:
        season (str): Season in format 'YYYY-YYYY' (e.g., '2017-2018')
        round_num (int): Round number (e.g., 17)
        
    Returns:
        list: List of dictionaries containing match information
    """
    # Construct the URL
    url = f"https://top14.lnr.fr/calendrier-et-resultats/{season}/j{round_num}"
    
    try:
        # Fetch the page
        headers = {
            'User-Agent': SCRAPING_CONFIG['user_agent']
        }
        response = requests.get(url, headers=headers, timeout=SCRAPING_CONFIG['timeout'])
        response.raise_for_status()
        
        # Parse the HTML
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find all match elements - these are typically in div elements with specific classes
        # Based on the example, we're looking for elements with class 'match-line__score'
        match_elements = soup.find_all('a', class_='match-line__score')
        
        matches = []
        
        # Load teams data
        teams_df = load_dataset('processed', 'teams.csv')
        
        if teams_df is None:
            print(f"Error: Could not load teams data. Skipping round {round_num}")
            return []
        
        for element in match_elements:
            # Extract match URL
            match_url = element.get('href', '')
            
            # Extract match ID from the URL - looking for pattern like /j17/8218-toulon-paris
            match_id_match = re.search(r'/j\d+/(\d+)-', match_url)
            if match_id_match:
                match_id = match_id_match.group(1)
            else:
                match_id = 'Unknown'
            
            # Find the match line to get team names
            match_line = element.find_parent('div', class_='match-line')
            
            if match_line:
                # Find team name elements
                team_name_elements = match_line.find_all('a', class_='club-line__name')
                
                if len(team_name_elements) >= 2:
                    home_team = team_name_elements[0].get_text(strip=True)
                    away_team = team_name_elements[1].get_text(strip=True)
                    
                    # Get venue from home team
                    venue = get_team_venue(home_team, teams_df)
                    
                    # The URL is already complete, no need to construct it
                    full_url = match_url
                    
                    matches.append({
                        'match_id': match_id,
                        'season': season,
                        'round': round_num,
                        'venue': venue,
                        'home_team': home_team,
                        'away_team': away_team,
                        'url': full_url,
                        'is_playoff': 0  # 0 = regular season, 1 = playoff/access match
                    })
        
        return matches
        
    except requests.RequestException as e:
        print(f"Error fetching {url}: {e}")
        return []
    except Exception as e:
        print(f"Error processing {url}: {e}")
        return []


def scrape_matches_list():
    """
    Main function to scrape and display match information for all seasons and rounds.
    """
    print("Scraping list of matches")
    all_matches = []
    
    # Scrape all seasons and rounds (1-26)
    for season in SEASONS:
        print(f"\nProcessing season: {season}")
        
        for round_num in range(1, 27):  # Rounds 1 to 26
            print(f"  Scraping round {round_num}...", end=" ")
            
            matches = scrape_matches_for_round(season, round_num)
            
            if matches:
                all_matches.extend(matches)
                print(f"Found {len(matches)} matches")
            else:
                print("No matches found")
            
            # Rate limiting to be respectful to the server
            time.sleep(SCRAPING_CONFIG['rate_limit_seconds'])
    
    # Load playoff matches
    print("\nLoading playoff matches...")
    playoff_matches = load_playoff_matches()
    print(f"  Found {len(playoff_matches)} playoff matches")
    
    # Combine both datasets
    all_matches.extend(playoff_matches)
    
    # Display summary
    print(f"\n" + "="*80)
    print(f"SCRAPING COMPLETE")
    regular_count = len(all_matches) - len(playoff_matches)
    print(f"Regular season matches: {regular_count}")
    print(f"Playoff matches: {len(playoff_matches)}")
    print(f"Total matches: {len(all_matches)}")
    print("="*80)
    
    if all_matches:
        # Show a sample of the data
        print("\nSample of collected data:")
        print("-" * 80)
        for i, match in enumerate(all_matches[:10], 1):  # Show first 10 matches
            print(f"Match {i}:")
            print(f"  Season: {match['season']}")
            print(f"  Round: {match['round']}")
            print(f"  Match ID: {match['match_id']}")
            print(f"  Venue: {match['venue']}")
            print(f"  Home Team: {match['home_team']}")
            print(f"  Away Team: {match['away_team']}")
            print(f"  URL: {match['url']}")
            print(f"  Is Playoff: {'Yes' if match['is_playoff'] == 1 else 'No'}")
            print("-" * 80)
        
        # Save to CSV file
        try:
            df = pd.DataFrame(all_matches)
            # Sort by season and round for better organization
            df = df.sort_values(['season', 'round', 'is_playoff'])
            
            # Save to data/processed directory
            result = save_to_csv(df, 'matches_list.csv', 'processed')
            if result:
                print(f"Successfully saved {len(all_matches)} matches to data/processed/matches.csv")
            else:
                print("Failed to save matches data")
        except Exception as e:
            print(f"Error saving to CSV: {e}")
    else:
        print("No matches found or an error occurred.")
        
    return df