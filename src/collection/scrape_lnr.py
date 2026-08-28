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
from utils import save_to_csv, extract_player_id


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

def extract_player_urls(soup: BeautifulSoup) -> list:
    """
    Extract all player profile URLs from a match compositions page.

    Structure: <a class="player-pitch player-pitch--position-N"
                  href="https://top14.lnr.fr/joueur/...">
    inside <div class="line-up__pitch-team">.

    Returns a deduplicated list of absolute player profile URLs.
    """
    seen = set()
    urls = []
    for a in soup.find_all('a', href=lambda h: h and '/joueur/' in h):
        href = a.get('href', '')
        if href.startswith('/'):
            href = 'https://top14.lnr.fr' + href
        if href not in seen:
            seen.add(href)
            urls.append(href)
    return urls


def scrape_one_match(
    session: requests.Session,
    driver,
    match_id: str,
    base_url: str,
    season: str,
    round_num: str,
    home_team: str,
    away_team: str,
    delay: float,
) -> Tuple[Dict, list, bool]:
    """
    Scrape all statistics for a single match.

    Uses requests for the main page (fast),
    and Selenium for the statistics page (JavaScript-rendered).

    Returns:
        Tuple of:
            - match_data dict
            - list of player profile URLs
            - verified_empty: True only if the statistics page loaded
              successfully AND both home_passes/away_passes were actually
              parsed (present, not missing) as exactly 0 — no real match
              has zero passes on both sides. False for any other outcome,
              including a page that failed to load/render in time — that's
              a timeout, not evidence the match has no data. (Do NOT use
              the "Aucune statistique disponible..." text or a timeout
              waiting for 'match-statistics__roster' as signals — verified
              by direct HTML comparison: that text is scoped to a "top
              players" sub-widget that's empty on both real and empty
              matches, and the roster wait target is present on empty
              matches too, so neither discriminates anything.)
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

    # --- 2. Compositions page (Selenium): collect player profile URLs ---
    player_urls = []
    compo_soup = get_soup_selenium(
        driver,
        build_page_url(base_url, "compositions"),
        'line-up__pitch-team',
        delay,
    )
    if compo_soup:
        player_urls = extract_player_urls(compo_soup)
    else:
        logger.warning(f"[{match_id}] Could not load compositions page")

    # --- 3. Statistics page (Selenium): team stats ---
    soup = get_soup_selenium(
        driver,
        build_page_url(base_url, "statistiques-du-match"),
        'match-statistics__roster',
        delay,
    )
    verified_empty = False
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

        # Verified empty: the passes stat bar was actually found and parsed
        # on BOTH sides (not absent — a render failure would leave these
        # keys missing from `data` entirely, not present-as-zero), and both
        # sides read exactly 0. No real 80-minute match has zero passes, so
        # this is LNR confirming no stats exist for this match — the same
        # criterion used to drop all-zero rows in the cleaning stage
        # (clean_dataset.py's Rule B), applied here at scrape time instead.
        if data.get('home_passes') == 0 and data.get('away_passes') == 0:
            verified_empty = True
            logger.info(f"[{match_id}] Verified empty — home_passes/away_passes both 0 on a loaded page")

    # --- 3. Bonus points ---
    home_bonus, away_bonus = calculate_bonus_points(
        season,
        data.get('home_score'),
        data.get('away_score'),
        data.get('home_tries'),
        data.get('away_tries'),
    )
    data['home_bonus_points'] = home_bonus
    data['away_bonus_points'] = away_bonus

    logger.info(f"[{match_id}] Scraped {len(data)} fields, {len(player_urls)} player URLs")
    return data, player_urls, verified_empty


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
        matches_df:   DataFrame with columns: match_id, url, season, round,
                      home_team, away_team
        output_csv:   Path to save match-level stats CSV

        delay:        Seconds between requests
        headless:     Run Chrome without a visible window
        save_incomplete: Save a _incomplete.csv for matches with missing fields

    Returns:
        Tuple of:
            - match stats DataFrame  (one row per match)
            - player records DataFrame  (one row per player per match)

    Example:
        from scrape_lnr import scrape_lnr
        import pandas as pd

        matches = pd.read_csv("data/matches.csv")
        stats_df, players_df = scrape_lnr(matches)
    """
    required = {'match_id', 'url', 'season', 'round', 'home_team', 'away_team'}
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
    all_player_urls = set()
    incomplete = []

    try:
        for idx, row in matches_df.iterrows():
            match_id  = str(row['match_id'])
            base_url  = str(row['url'])
            season    = str(row['season'])
            round_num = str(row['round'])
            home_team = str(row['home_team'])
            away_team = str(row['away_team'])

            logger.info(f"[{idx + 1}/{total}] {season} R{round_num} — match {match_id}")

            try:
                import signal

                def timeout_handler(signum, frame):
                    raise TimeoutError(f"Match {match_id} took too long to scrape")

                signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(120)
                timeout_active = True
            except (ImportError, AttributeError):
                timeout_active = False

            try:
                match_data, player_urls, verified_empty = scrape_one_match(
                    session, driver, match_id, base_url,
                    season, round_num, home_team, away_team, delay
                )
                results.append(match_data)
                all_player_urls.update(player_urls)

                critical = [
                    'match_date', 'match_time', 'home_score', 'away_score',
                    'home_tries', 'away_tries',
                    'home_possession', 'away_possession',
                ]
                missing_fields = [f for f in critical if f not in match_data]
                if missing_fields:
                    # status reflects ONLY this attempt's own outcome — never
                    # inferred from season/round/other matches. confirmed_no_data
                    # requires this specific page load to have positively shown
                    # LNR has no stats; anything else (timeout, render failure,
                    # exception) is timeout_unverified and stays retry-eligible.
                    status = 'confirmed_no_data' if verified_empty else 'timeout_unverified'
                    incomplete.append({
                        'match_id':       match_id,
                        'season':         season,
                        'round':          round_num,
                        'missing_fields': ', '.join(missing_fields),
                        'fields_scraped': len(match_data),
                        'status':         status,
                    })
                    logger.warning(f"[{match_id}] Incomplete ({status}) — missing: {missing_fields}")

            except TimeoutError as e:
                logger.error(f"[{match_id}] Timeout: {e}")
                continue
            except Exception as e:
                logger.error(f"[{match_id}] Error: {e}\n{traceback.format_exc()}")
                continue
            finally:
                if timeout_active:
                    signal.alarm(0)

            # Save progress every 10 matches
            if (idx + 1) % 10 == 0:
                save_to_csv(pd.DataFrame(results), f"{output_csv}_progress.csv", "processed")
                logger.info(f"Progress saved at match {idx + 1}")

    finally:
        driver.quit()
        logger.info("Chrome WebDriver closed")

    # --- Save final outputs ---
    results_df = pd.DataFrame(results)
    if not results_df.empty:
        # match_id is built as a str in scrape_one_match(); cast back to int
        # so this return value's dtype matches every CSV-loaded DataFrame
        # elsewhere in the pipeline (pd.read_csv infers int64). Otherwise a
        # match_id.isin(...) comparison against an int set silently matches
        # nothing instead of raising, e.g. in the retry-merge step.
        results_df["match_id"] = results_df["match_id"].astype(int)

    result_path = save_to_csv(results_df, output_csv, "processed")
    if result_path:
        logger.info(f"Saved {len(results_df)} match records to '{result_path}'")

    if all_player_urls:
        # Merge with any existing player_urls.csv (keyed by canonical player
        # ID) instead of overwriting it — otherwise a partial run (e.g. a
        # retry against a handful of matches) clobbers the full master list
        # with just the URLs harvested in this one call.
        merged_by_id = {}
        existing_urls_path = Path(__file__).parent.parent.parent / "data" / "processed" / "player_urls.csv"
        if existing_urls_path.exists():
            existing = pd.read_csv(existing_urls_path)
            for u in existing["player_url"].dropna():
                pid = extract_player_id(u)
                if pid:
                    merged_by_id[pid] = u
        for u in all_player_urls:
            pid = extract_player_id(u)
            if pid and pid not in merged_by_id:
                merged_by_id[pid] = u

        urls_df = pd.DataFrame(sorted(merged_by_id.values()), columns=["player_url"])
        urls_path = save_to_csv(urls_df, "player_urls.csv", "processed")
        if urls_path:
            logger.info(f"Saved {len(urls_df)} unique player URLs to '{urls_path}'")

    if incomplete:
        print(f"\n{'='*70}")
        print(f"⚠️  {len(incomplete)} INCOMPLETE MATCHES")
        print(f"{'='*70}")
        for item in incomplete:
            print(f"  Match {item['match_id']:10s} — missing: {item['missing_fields']}")
        print(f"{'='*70}\n")
        if save_incomplete:
            incomplete_filename = output_csv.replace('.csv', '_incomplete.csv')
            save_to_csv(pd.DataFrame(incomplete), incomplete_filename, "processed")
    else:
        logger.info("✅ All matches scraped with complete data")

    return results_df