"""
LNR Top 14 Match Statistics Scraper

Scrapes match statistics from the LNR website for French Top 14 rugby matches.
Uses Selenium to handle JavaScript-rendered player statistics.

Requirements:
    pip install pandas requests beautifulsoup4 selenium webdriver-manager

Usage:
    import pandas as pd
    from scrape_lnr import scrape_lnr

    matches_df = pd.read_csv("data/matches.csv")
    stats_df = scrape_lnr(matches_df, output_csv="data/match_stats.csv")

Expected columns in input DataFrame:
    - match_id:  e.g. "10954"
    - url:       e.g. "https://top14.lnr.fr/feuille-de-match/2024-2025/j12/10954-paris-perpignan"
                 The compositions and statistics pages are derived by appending
                 "/compositions" and "/statistiques-du-match" to this base URL.
    - season:    e.g. "2024-2025"  (used only for bonus point calculation)
"""

import pandas as pd
import requests
from bs4 import BeautifulSoup
import re
import time
import logging
import traceback
from typing import Dict, Optional, Tuple
from pathlib import Path
import sys

# Add the src directory to the path so we can import utils
sys.path.append(str(Path(__file__).parent.parent))
from utils import save_to_csv

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, WebDriverException
    from webdriver_manager.chrome import ChromeDriverManager
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# =============================================================================
# URL HELPER
# =============================================================================

def build_page_url(base_url: str, page: str) -> str:
    """
    Append a page suffix to a match base URL.

    Args:
        base_url:  e.g. "https://top14.lnr.fr/.../10954-paris-perpignan"
        page:      e.g. "compositions" or "statistiques-du-match"

    Returns:
        Full URL for the requested page
    """
    return f"{base_url.rstrip('/')}/{page}"


# =============================================================================
# SELENIUM / HTTP HELPERS
# =============================================================================

def init_driver(headless: bool = True):
    """
    Initialize and return a Selenium Chrome WebDriver.

    Args:
        headless: Run Chrome without a visible window

    Returns:
        Selenium WebDriver instance
    """
    if not SELENIUM_AVAILABLE:
        raise ImportError(
            "Selenium is not installed. Run: pip install selenium webdriver-manager"
        )
    options = Options()
    if headless:
        options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')
    options.add_argument(
        '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    )
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    logger.info("Chrome WebDriver initialized")
    return driver


def get_soup(session: requests.Session, url: str, delay: float) -> Optional[BeautifulSoup]:
    """
    Fetch a page with requests and return a BeautifulSoup object.

    Args:
        session: requests.Session to use
        url:     URL to fetch
        delay:   Seconds to wait before the request

    Returns:
        BeautifulSoup or None on failure
    """
    try:
        time.sleep(delay)
        response = session.get(url, timeout=10)
        response.raise_for_status()
        return BeautifulSoup(response.content, 'html.parser')
    except requests.RequestException as e:
        logger.error(f"HTTP error fetching {url}: {e}")
        return None


def get_soup_selenium(driver, url: str, wait_for_class: str, delay: float) -> Optional[BeautifulSoup]:
    """
    Fetch a JavaScript-rendered page with Selenium and return a BeautifulSoup object.

    Args:
        driver:          Selenium WebDriver
        url:             URL to fetch
        wait_for_class:  CSS class to wait for before reading HTML
        delay:           Seconds to wait before loading

    Returns:
        BeautifulSoup or None on failure
    """
    try:
        time.sleep(delay)
        logger.info(f"Loading URL: {url}")
        driver.get(url)
        
        # Set a maximum timeout for the wait
        start_time = time.time()
        max_wait = 15  # Maximum 15 seconds total wait time
        
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CLASS_NAME, wait_for_class))
            )
            logger.info(f"Found element {wait_for_class} on {url}")
        except TimeoutException:
            logger.warning(f"Timeout waiting for '{wait_for_class}' on {url}")
            # Continue anyway and return what we have
            pass
        
        # Make sure we don't wait too long overall
        elapsed = time.time() - start_time
        if elapsed < max_wait:
            time.sleep(min(2, max_wait - elapsed))  # Extra wait but respect max timeout
        
        return BeautifulSoup(driver.page_source, 'html.parser')
    except WebDriverException as e:
        logger.error(f"Selenium WebDriver error on {url}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching {url}: {e}")
        return None


# =============================================================================
# EXTRACTION FUNCTIONS
# =============================================================================

def extract_date_time(soup: BeautifulSoup) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract match date (YYYY-MM-DD) and time (HH:MM) from the main match page.
    """
    try:
        div = soup.find('div', class_='match-header__season-day')
        if not div:
            logger.warning("Date/time element not found")
            return None, None

        text = div.get_text(strip=True)

        date_match = re.search(r'(\d{2})/(\d{2})/(\d{4})', text)
        formatted_date = (
            f"{date_match.group(3)}-{date_match.group(2)}-{date_match.group(1)}"
            if date_match else None
        )

        time_match = re.search(r'(\d{1,2})h(\d{2})', text)
        formatted_time = (
            f"{time_match.group(1).zfill(2)}:{time_match.group(2)}"
            if time_match else None
        )

        return formatted_date, formatted_time

    except Exception as e:
        logger.error(f"Error extracting date/time: {e}")
        return None, None


def extract_score(soup: BeautifulSoup) -> Tuple[Optional[int], Optional[int]]:
    """
    Extract home and away scores from the main match page.
    """
    try:
        div = soup.find('div', class_='title title--large title--textured title--centered')
        if not div:
            logger.warning("Score element not found")
            return None, None

        scores = re.findall(r'\d+', div.get_text(strip=True))
        if len(scores) >= 2:
            return int(scores[0]), int(scores[1])
        return None, None

    except Exception as e:
        logger.error(f"Error extracting score: {e}")
        return None, None


def extract_referee(soup: BeautifulSoup) -> Optional[str]:
    """
    Extract the referee name from the compositions page.
    """
    try:
        for block in soup.find_all('div', class_='player-block__infos'):
            position = block.find('p', class_='player-block__position')
            if position and 'Arbitre Central' in position.get_text():
                name = block.find('p', class_='player-block__name')
                if name:
                    return name.get_text(strip=True)
        return None

    except Exception as e:
        logger.error(f"Error extracting referee: {e}")
        return None


def extract_stat_bar(soup: BeautifulSoup, stat_title: str) -> Tuple[Optional[int], Optional[int]]:
    """
    Extract a home/away integer statistic from a stats-bar element.

    Args:
        soup:       BeautifulSoup of the statistics page
        stat_title: French label of the stat, e.g. "Essais accordés"

    Returns:
        (home_value, away_value) or (None, None) if not found
    """
    try:
        for bar in soup.find_all('div', class_='stats-bar'):
            title_div = bar.find('div', class_='stats-bar__title')
            if title_div and stat_title in title_div.get_text():
                left  = bar.find('div', class_='stats-bar__val stats-bar__val--left')
                right = bar.find('div', class_='stats-bar__val stats-bar__val--right')

                def to_int(el):
                    if el:
                        try:
                            return int(el.get_text(strip=True))
                        except (ValueError, TypeError):
                            pass
                    return None

                return to_int(left), to_int(right)

        logger.debug(f"Stat bar '{stat_title}' not found")
        return None, None

    except Exception as e:
        logger.error(f"Error extracting stat bar '{stat_title}': {e}")
        return None, None


def extract_percentage_stat(soup: BeautifulSoup, stat_title: str) -> Tuple[Optional[int], Optional[int]]:
    """
    Extract a home/away percentage statistic from a stats-bar element.
    Returns integers (e.g. 56, not 0.56).
    """
    try:
        for bar in soup.find_all('div', class_='stats-bar'):
            title_div = bar.find('div', class_='stats-bar__title')
            if title_div and stat_title in title_div.get_text():
                left  = bar.find('div', class_='stats-bar__val stats-bar__val--left')
                right = bar.find('div', class_='stats-bar__val stats-bar__val--right')

                def to_pct(el):
                    if el:
                        try:
                            return int(float(el.get_text(strip=True).replace('%', '').strip()))
                        except (ValueError, TypeError):
                            pass
                    return None

                return to_pct(left), to_pct(right)

        logger.debug(f"Percentage stat '{stat_title}' not found")
        return None, None

    except Exception as e:
        logger.error(f"Error extracting percentage stat '{stat_title}': {e}")
        return None, None


def extract_cards(soup: BeautifulSoup) -> Dict[str, int]:
    """
    Extract yellow and red card counts for both teams.
    Always returns all four keys (defaults to 0).
    """
    cards = {
        'home_yellow_cards': 0,
        'away_yellow_cards': 0,
        'home_red_cards':    0,
        'away_red_cards':    0,
    }
    try:
        container = soup.find('div', class_='match-statistics__cards')
        if not container:
            logger.debug("Cards container not found — no cards given in this match")
            return cards

        teams = container.find_all('div', class_='match-statistics__cards-team')
        if len(teams) < 2:
            return cards

        def count_cards(section, color):
            div = section.find('div', class_=f'stats-cards-fault stats-cards-fault--{color}')
            if div:
                inner = div.find('div', class_='stats-cards-fault__container')
                if inner:
                    card = inner.find('div', class_='stats-cards-fault__card')
                    if card:
                        text = card.get_text(strip=True)
                        if text.isdigit():
                            return int(text)
            return 0

        cards['home_yellow_cards'] = count_cards(teams[0], 'yellow')
        cards['away_yellow_cards'] = count_cards(teams[1], 'yellow')
        cards['home_red_cards']    = count_cards(teams[0], 'red')
        cards['away_red_cards']    = count_cards(teams[1], 'red')

    except Exception as e:
        logger.error(f"Error extracting cards: {e}")

    return cards


def extract_player_stats(soup: BeautifulSoup) -> Dict[str, int]:
    """
    Aggregate individual player statistics by team.
    Requires JavaScript-rendered HTML (Selenium).

    Stats extracted per team:
        - lineBreak       → line_breaks      (Franchissements)
        - offload         → offloads
        - breakdownSteals → turnovers        (Ballons grattés)

    Always returns all six keys (defaults to 0) for CSV consistency.
    """
    stats = {
        'home_line_breaks': 0,
        'away_line_breaks': 0,
        'home_offloads':    0,
        'away_offloads':    0,
        'home_turnovers':   0,
        'away_turnovers':   0,
    }
    try:
        # Set a timeout for this function to prevent hanging
        import signal
        
        def timeout_handler(signum, frame):
            raise TimeoutError("Player stats extraction took too long")
        
        # Set a 30-second timeout for player stats extraction
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(30)  # 30 seconds max
        timeout_active = True
        
        try:
            rosters = soup.find_all('div', class_='match-statistics__roster')
            if len(rosters) < 2:
                logger.warning(f"Found {len(rosters)} roster section(s), expected 2")
                return stats

            def sum_by_class(roster, modifier):
                total = 0
                # Use a more efficient approach - find all div elements first, then filter
                for cell in roster.find_all('div'):
                    # Check if the cell has the right class
                    cell_classes = cell.get('class', [])
                    if cell_classes and any(f'player-row__cell--{modifier}' in cls for cls in cell_classes):
                        text = ''.join(c for c in cell.get_text(strip=True) if c.isdigit())
                        if text:
                            total += int(text)
                return total

            home, away = rosters[0], rosters[1]

            stats['home_line_breaks'] = sum_by_class(home, 'lineBreak')
            stats['home_offloads']    = sum_by_class(home, 'offload')
            stats['home_turnovers']   = sum_by_class(home, 'breakdownSteals')
            stats['away_line_breaks'] = sum_by_class(away, 'lineBreak')
            stats['away_offloads']    = sum_by_class(away, 'offload')
            stats['away_turnovers']   = sum_by_class(away, 'breakdownSteals')

            logger.info(f"Player stats: {stats}")

        finally:
            if timeout_active:
                signal.alarm(0)

    except TimeoutError as e:
        logger.error(f"Timeout in player stats extraction: {e}")
    except Exception as e:
        logger.error(f"Error extracting player stats: {e}\n{traceback.format_exc()}")

    return stats


def calculate_bonus_points(
    season: str,
    home_score: Optional[int],
    away_score: Optional[int],
    home_tries: Optional[int],
    away_tries: Optional[int],
) -> Tuple[int, int]:
    """
    Calculate offensive and defensive bonus points for both teams.

    Rules:
        Offensive:  team scores ≥ 3 more tries than opponent → +1
        Defensive:  losing team loses by ≤ 5 pts (from 2023-24 onwards)
                                          or ≤ 7 pts (before 2023-24) → +1

    Returns:
        (home_bonus, away_bonus)
    """
    if None in (home_score, away_score, home_tries, away_tries):
        return 0, 0

    home_bonus = 0
    away_bonus = 0

    season_year = int(season.split('-')[0])
    threshold = 5 if season_year >= 2023 else 7

    if home_tries >= away_tries + 3:
        home_bonus += 1
    if away_tries >= home_tries + 3:
        away_bonus += 1

    diff = abs(home_score - away_score)
    if diff <= threshold:
        if home_score < away_score:
            home_bonus += 1
        elif away_score < home_score:
            away_bonus += 1

    return home_bonus, away_bonus


# =============================================================================
# SINGLE-MATCH SCRAPER
# =============================================================================

def scrape_one_match(
    session: requests.Session,
    driver,
    match_id: str,
    base_url: str,
    season: str,
    delay: float,
) -> Dict:
    """
    Scrape all statistics for a single match.

    Uses requests for the main and compositions pages (fast),
    and Selenium for the statistics page (JavaScript-rendered).

    Args:
        session:   requests.Session
        driver:    Selenium WebDriver
        match_id:  Match identifier (for logging)
        base_url:  Full match URL from matches.csv
        season:    Season string for bonus point calculation
        delay:     Seconds between requests

    Returns:
        Dictionary of all scraped statistics
    """
    data = {'match_id': match_id}

    # --- 1. Main page: date, time, score ---
    soup = get_soup(session, base_url, delay)
    if soup:
        date, match_time = extract_date_time(soup)
        if date:        data['match_date'] = date
        if match_time:  data['match_time'] = match_time

        home_score, away_score = extract_score(soup)
        if home_score is not None: data['home_score'] = home_score
        if away_score is not None: data['away_score'] = away_score
    else:
        logger.warning(f"[{match_id}] Failed to fetch main page")

    # --- 2. Compositions page: referee ---
    soup = get_soup(session, build_page_url(base_url, "compositions"), delay)
    if soup:
        referee = extract_referee(soup)
        if referee: data['referee'] = referee
    else:
        logger.warning(f"[{match_id}] Failed to fetch compositions page")

    # --- 3. Statistics page (Selenium): all team stats + player stats ---
    soup = get_soup_selenium(
        driver,
        build_page_url(base_url, "statistiques-du-match"),
        'match-statistics__roster',
        delay,
    )
    if not soup:
        logger.warning(f"[{match_id}] Failed to fetch statistics page — stats will be missing")
    else:
        def add(home_key, away_key, home_val, away_val):
            if home_val is not None: data[home_key] = home_val
            if away_val is not None: data[away_key] = away_val

        add('home_tries', 'away_tries',
            *extract_stat_bar(soup, "Essais accordés"))

        add('home_possession', 'away_possession',
            *extract_percentage_stat(soup, "Possession de la balle"))
        add('home_territory', 'away_territory',
            *extract_percentage_stat(soup, "Occupation"))
        add('home_possession_own_half', 'away_possession_own_half',
            *extract_percentage_stat(soup, "Possession dans son camp"))
        add('home_possession_opponent_half', 'away_possession_opponent_half',
            *extract_percentage_stat(soup, "Possession dans le camp adverse"))
        add('home_possession_opponent_22', 'away_possession_opponent_22',
            *extract_percentage_stat(soup, "Possession 22m adverses"))

        add('home_scrums_played', 'away_scrums_played',
            *extract_stat_bar(soup, "Mêlées obtenues"))
        add('home_scrums_won', 'away_scrums_won',
            *extract_stat_bar(soup, "Mêlées gagnées"))
        add('home_scrums_lost', 'away_scrums_lost',
            *extract_stat_bar(soup, "Mêlées perdues"))
        add('home_scrums_reset', 'away_scrums_reset',
            *extract_stat_bar(soup, "Mêlées refaites"))

        add('home_lineouts_played', 'away_lineouts_played',
            *extract_stat_bar(soup, "Touches obtenues"))
        add('home_lineouts_own_won', 'away_lineouts_own_won',
            *extract_stat_bar(soup, "Touches gagnées sur son propre lancer"))
        add('home_lineouts_opponents_won', 'away_lineouts_opponents_won',
            *extract_stat_bar(soup, "Touches gagnées sur lancer adverse"))

        add('home_knockons', 'away_knockons',
            *extract_stat_bar(soup, "En-avant commis"))
        add('home_penalties_scored', 'away_penalties_scored',
            *extract_stat_bar(soup, "Pénalités réussies"))
        add('home_penalties_conceded', 'away_penalties_conceded',
            *extract_stat_bar(soup, "Pénalités concédées"))

        data.update(extract_cards(soup))

        add('home_tackles_made', 'away_tackles_made',
            *extract_stat_bar(soup, "Plaquages réussis"))
        add('home_tackles_off_made', 'away_tackles_off_made',
            *extract_stat_bar(soup, "Plaquages offensifs réussis"))
        add('home_tackles_missed', 'away_tackles_missed',
            *extract_stat_bar(soup, "Plaquages manqués"))
        add('home_kicks', 'away_kicks',
            *extract_stat_bar(soup, "Ballons joués au pied"))
        add('home_passes', 'away_passes',
            *extract_stat_bar(soup, "Ballons passés"))

        data.update(extract_player_stats(soup))

    # --- 4. Bonus points (calculated, not scraped) ---
    home_bonus, away_bonus = calculate_bonus_points(
        season,
        data.get('home_score'),
        data.get('away_score'),
        data.get('home_tries'),
        data.get('away_tries'),
    )
    data['home_bonus_points'] = home_bonus
    data['away_bonus_points'] = away_bonus

    logger.info(f"[{match_id}] Scraped {len(data)} fields")
    return data


# =============================================================================
# PUBLIC ENTRY POINT
# =============================================================================

def scrape_lnr(
    matches_df: pd.DataFrame,
    output_csv: str = "regular_season_stats.csv",
    delay: float = 1.0,
    headless: bool = True,
    save_incomplete: bool = True,
) -> pd.DataFrame:
    """
    Scrape LNR match statistics for all matches in the input DataFrame.

    This is the only function to import from your main script.

    Args:
        matches_df:       DataFrame with columns: match_id, url, season
        output_csv:       Filename to save the results CSV (default: "regular_season_stats.csv")
        delay:            Seconds between requests (be respectful to the server)
        headless:         Run Chrome without a visible window
        save_incomplete:  If True, also save a _incomplete.csv listing matches
                          with missing critical fields

    Returns:
        DataFrame containing all scraped statistics

    Example:
        from scrape_lnr import scrape_lnr
        import pandas as pd

        matches = pd.read_csv("data/matches.csv")
        stats   = scrape_lnr(matches, output_csv="regular_season_stats.csv")
    """
    required = {'match_id', 'url', 'season'}
    missing_cols = required - set(matches_df.columns)
    if missing_cols:
        raise ValueError(f"Input DataFrame is missing columns: {missing_cols}")

    total = len(matches_df)
    logger.info(f"Starting scrape of {total} matches")

    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })

    driver = init_driver(headless=headless)

    results = []
    incomplete = []

    try:
        for idx, row in matches_df.iterrows():
            match_id = str(row['match_id'])
            base_url = str(row['url'])
            season   = str(row['season'])

            logger.info(f"[{idx + 1}/{total}] {season} — match {match_id}")

            try:
                # Set a timeout for the entire match scraping process
                try:
                    import signal
                    
                    def timeout_handler(signum, frame):
                        raise TimeoutError(f"Match {match_id} took too long to scrape")
                    
                    # Set a 2-minute timeout per match (120 seconds)
                    signal.signal(signal.SIGALRM, timeout_handler)
                    signal.alarm(120)  # 2 minutes max per match
                    timeout_active = True
                except (ImportError, AttributeError):
                    # signal module not available, proceed without timeout
                    timeout_active = False
                
                try:
                    match_data = scrape_one_match(
                        session, driver, match_id, base_url, season, delay
                    )
                    results.append(match_data)

                    critical = [
                        'match_date', 'match_time', 'home_score', 'away_score',
                        'referee', 'home_tries', 'away_tries',
                        'home_possession', 'away_possession',
                    ]
                    missing_fields = [f for f in critical if f not in match_data]
                    if missing_fields:
                        incomplete.append({
                            'match_id':       match_id,
                            'missing_fields': ', '.join(missing_fields),
                            'fields_scraped': len(match_data),
                        })
                        logger.warning(f"[{match_id}] Incomplete — missing: {missing_fields}")

                finally:
                    # Disable the alarm if it was set
                    if timeout_active:
                        signal.alarm(0)

            except TimeoutError as e:
                logger.error(f"[{match_id}] Timeout error: {e}")
                continue
            except Exception as e:
                logger.error(
                    f"[{match_id}] Unexpected error: {e}\n{traceback.format_exc()}"
                )
                continue

            # Save progress every 10 matches to avoid losing data
            if (idx + 1) % 10 == 0:
                progress_df = pd.DataFrame(results)
                progress_path = save_to_csv(progress_df, f"{output_csv}_progress.csv", "processed")
                if progress_path:
                    logger.info(f"Progress saved: {len(progress_df)} matches saved to '{progress_path}'")

    finally:
        driver.quit()
        logger.info("Chrome WebDriver closed")

    results_df = pd.DataFrame(results)
    
    # Save main results using save_to_csv function
    result_path = save_to_csv(results_df, output_csv, "processed")
    if result_path:
        logger.info(f"Saved {len(results_df)} matches to '{result_path}'")
    else:
        logger.error(f"Failed to save {len(results_df)} matches")

    if incomplete:
        print(f"\n{'='*70}")
        print(f"⚠️  {len(incomplete)} INCOMPLETE MATCHES")
        print(f"{'='*70}")
        for item in incomplete:
            print(f"  Match {item['match_id']:10s} — missing: {item['missing_fields']}")
        print(f"{'='*70}\n")
        if save_incomplete:
            incomplete_filename = output_csv.replace('.csv', '_incomplete.csv')
            incomplete_path = save_to_csv(pd.DataFrame(incomplete), incomplete_filename, "processed")
            if incomplete_path:
                logger.info(f"Incomplete list saved to '{incomplete_path}'")
            else:
                logger.error(f"Failed to save incomplete list")
    else:
        logger.info("✅ All matches scraped with complete data")

    return results_df