import time
import requests
from constants import SCRAPING_CONFIG

def scrape_match_page(match_url):
    """
    Scrape a single match page with rate limiting
    """
    headers = {
        'User-Agent': SCRAPING_CONFIG['user_agent']
    }
    
    try:
        response = requests.get(
            match_url, 
            headers=headers,
            timeout=scraping_config['timeout']
        )
        response.raise_for_status()
        
        # Save raw HTML
        # ... your parsing code ...
        
        # IMPORTANT: Rate limiting
        time.sleep(scraping_config['rate_limit_seconds'])
        
        return response.text
        
    except requests.exceptions.RequestException as e:
        print(f"Error scraping {match_url}: {e}")
        return None