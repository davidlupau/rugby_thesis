import requests
from bs4 import BeautifulSoup
import re
import time

def scrape_lnr_match(url):
    """Scrape a single LNR match page"""
    
    headers = {'User-Agent': 'UniversityResearchBot/1.0 (BSc Thesis)'}
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        print(f"❌ Failed to access {url}")
        return None
    
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Extract match data
    match_data = {}
    
    # 1. Get team names from page title
    title = soup.find('title').text
    # Title format: "LOU Rugby - Stade Rochelais - J15 - 2023-2024 | Top 14 - Site Officiel"
    title_parts = title.split(' | ')[0]  # Remove "Top 14 - Site Officiel"
    teams_and_info = title_parts.split(' - ')
    
    if len(teams_and_info) >= 2:
        match_data['home_team'] = teams_and_info[0].strip()
        match_data['away_team'] = teams_and_info[1].strip()
    
    # Alternative: Get team names from img alt attributes (more reliable)
    team_imgs = soup.find_all('img', alt=True)
    team_names_from_imgs = []
    for img in team_imgs:
        alt = img.get('alt')
        # Skip common non-team images
        if alt and alt not in ['TOP 14', 'Parier', 'My Rugby', 'Logo MyRugby', '']:
            # Check if it looks like a team name (not a generic description)
            if len(alt) > 3 and 'avantages' not in alt.lower() and 'logo' not in alt.lower():
                team_names_from_imgs.append(alt)
    
    # First two team images should be home and away
    if len(team_names_from_imgs) >= 2:
        match_data['home_team'] = team_names_from_imgs[0]
        match_data['away_team'] = team_names_from_imgs[1]
    
    # 2. Get score
    score_div = soup.find('div', class_='title title--large title--textured title--centered')
    if score_div:
        score_text = score_div.text.strip()
        # Format: "28 - 17" or "28 – 17"
        scores = re.findall(r'\d+', score_text)
        if len(scores) >= 2:
            match_data['home_score'] = int(scores[0])
            match_data['away_score'] = int(scores[1])
    
    # 3. Get date, time, round
    season_day_div = soup.find('div', class_='match-header__season-day')
    if season_day_div:
        text = season_day_div.text.strip()
        # Format: " Match terminé - J15 - 17/02/2024 - 15h00 "
        
        # Extract round (J15)
        round_match = re.search(r'J(\d+)', text)
        if round_match:
            match_data['round'] = int(round_match.group(1))
        
        # Extract date (17/02/2024)
        date_match = re.search(r'(\d{2}/\d{2}/\d{4})', text)
        if date_match:
            match_data['date'] = date_match.group(1)
        
        # Extract time (15h00)
        time_match = re.search(r'(\d{2}h\d{2})', text)
        if time_match:
            match_data['time'] = time_match.group(1)
    
    # 4. Get match_id from URL
    # URL format: .../2023-2024/j15/10356-lyon-la-rochelle
    match_data['match_id'] = url.split('/')[-1].split('-')[0]
    
    # 5. Get season from URL
    season_match = re.search(r'/(\d{4}-\d{4})/', url)
    if season_match:
        match_data['season'] = season_match.group(1)
    
    return match_data


# TEST with your 3 URLs
test_urls = [
    'https://top14.lnr.fr/feuille-de-match/2023-2024/j15/10356-lyon-la-rochelle',
    'https://top14.lnr.fr/feuille-de-match/2018-2019/j19/8671-bordeaux-begles-paris',
    'https://top14.lnr.fr/feuille-de-match/2021-2022/j23/9896-brive-lyon',
]

print("="*70)
print("TESTING LNR SCRAPER")
print("="*70)

results = []

for url in test_urls:
    print(f"\n📍 Scraping: {url}")
    
    match_data = scrape_lnr_match(url)
    
    if match_data:
        print(f"✅ SUCCESS!")
        print(f"   Season: {match_data.get('season')}")
        print(f"   Round: J{match_data.get('round')}")
        print(f"   Date: {match_data.get('date')} at {match_data.get('time')}")
        print(f"   Home: {match_data.get('home_team')}")
        print(f"   Away: {match_data.get('away_team')}")
        print(f"   Score: {match_data.get('home_score')} - {match_data.get('away_score')}")
        print(f"   Match ID: {match_data.get('match_id')}")
        
        results.append(match_data)
    else:
        print(f"❌ FAILED")
    
    time.sleep(2)  # Rate limiting

print("\n" + "="*70)
print("CONSISTENCY CHECK:")
print("="*70)

# Check if team names are consistent
all_teams = set()
for match in results:
    all_teams.add(match.get('home_team'))
    all_teams.add(match.get('away_team'))

print(f"\nUnique teams found: {sorted(all_teams)}")
print(f"\nTotal matches scraped: {len(results)}")