import requests
import pandas as pd
from bs4 import BeautifulSoup
import time
from pathlib import Path
from typing import Union

# Importing your utility function from the project root
# Assuming this file is in src/collection/ and utils.py is in root/
import sys
project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))
from utils import save_to_csv

def get_players_from_wiki(url):
    """Scrapes a single Wikipedia page for player names."""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    players = set()
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            return players
        
        soup = BeautifulSoup(response.content, 'html.parser')
        lineup_columns = soup.find_all('td', style=lambda v: v and 'width:50%' in v.replace(' ', ''))

        for col in lineup_columns:
            lineup_table = col.find('table')
            if not lineup_table: continue
            
            for row in lineup_table.find_all('tr'):
                cols = row.find_all('td')
                if len(cols) >= 3:
                    name_cell = cols[2]
                    if any(x in name_cell.text for x in ["Replacements:", "Substitutes:", "Coach"]):
                        continue
                    
                    a_tag = name_cell.find('a')
                    player_name = a_tag.get_text().strip() if a_tag else name_cell.get_text().split('(')[0].strip()
                    
                    if player_name:
                        players.add(player_name)
        return players
    except Exception as e:
        print(f"Error scraping {url}: {e}")
        return players

def scrape_international_windows(df_windows: pd.DataFrame) -> pd.DataFrame:
    """
    Scrapes players from URLs in the DataFrame and automatically 
    saves the result to data/processed/player_callups.csv.
    """
    all_records = []
    
    print("Scraping international player call-ups from Wikipedia...")
    
    for _, row in df_windows.iterrows():
        url = row['url']
        window_id = row['int_window_id']
        season = row['season']
        
        if pd.isna(url) or 'wiki' not in str(url):
            continue
            
        print(f"Processing {window_id} ({season})...")
        player_names = get_players_from_wiki(url)
        
        for name in player_names:
            all_records.append({
                'player_name': name,
                'int_window_id': window_id,
                'season': season,
                'competition': row['competition']
            })
        
        time.sleep(1.2)
    
    df_results = pd.DataFrame(all_records)

    # DIRECT INTEGRATION OF SAVING LOGIC
    if not df_results.empty:
        # Calls your utils.py function
        save_to_csv(
            data=df_results, 
            file_name="player_callups.csv", 
            folder_name="processed"
        )
    else:
        print("Warning: Scraper returned no data. No file was saved.")
        
    return df_results