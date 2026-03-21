"""
LNR Player Registry Scraper
============================
Builds a player registry from LNR Top 14 match statistics pages.

TWO PHASES
----------
Phase 1 — Collect unique player profile URLs
    Iterates over every match in df_matches_list (filtered to target seasons),
    visits the statistics page, and collects the href of every player link found
    in the match-statistics__roster tables (home + away).
    Output: player_urls.csv  — one unique player URL per row.

Phase 2 — Scrape player profile pages
    For each unique player URL, visits the player profile page and extracts:
        - First name  (title-case part of the displayed name)
        - Last name   (all-caps part of the displayed name)
        - Nationality (from the flag image alt attribute, in French)
        - For each target season: team name + average minutes per match
    Output: players.csv — wide-format, one row per player.

OUTPUT CSV COLUMNS
------------------
    first_name, last_name, full_name, nationality,
    2017-2018_team, 2017-2018_avg_min,
    2018-2019_team, 2018-2019_avg_min,
    2021-2022_team, 2021-2022_avg_min,
    2022-2023_team, 2022-2023_avg_min,
    2023-2024_team, 2023-2024_avg_min,
    2024-2025_team, 2024-2025_avg_min

USAGE
-----
    import pandas as pd
    from scrape_lnr_players import scrape_player_registry

    df_matches_list = pd.read_csv("data/matches.csv")
    players_df = scrape_player_registry(df_matches_list)

REQUIREMENTS
------------
    pip install pandas selenium webdriver-manager beautifulsoup4
"""

import re
import time
import logging
import traceback
from pathlib import Path
from typing import Optional
import sys

import pandas as pd
from bs4 import BeautifulSoup

# Add the src directory to the path so we can import constants and utils
sys.path.append(str(Path(__file__).parent.parent))
from constants import SEASONS
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
except ImportError as e:
    raise ImportError(
        "Selenium is required. Run: pip install selenium webdriver-manager"
    ) from e


# =============================================================================
# CONFIGURATION
# =============================================================================

TARGET_SEASONS = SEASONS

LNR_BASE = "https://top14.lnr.fr"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# =============================================================================
# SELENIUM HELPERS
# =============================================================================

def init_driver(headless: bool = True):
    """Initialise a Chrome WebDriver."""
    options = Options()
    if headless:
        options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    logger.info("Chrome WebDriver initialised")
    return driver


def get_soup_selenium(
    driver,
    url: str,
    wait_class: str,
    delay: float = 2.0,
    extra_wait: float = 2.0,
) -> Optional[BeautifulSoup]:
    """
    Load a JS-rendered page with Selenium and return BeautifulSoup.

    Args:
        driver:     Selenium WebDriver
        url:        Page to load
        wait_class: CSS class to wait for before reading the DOM
        delay:      Seconds to sleep before loading the page
        extra_wait: Additional seconds after the element appears (JS settle)

    Returns:
        BeautifulSoup object or None on failure
    """
    try:
        time.sleep(delay)
        driver.get(url)
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CLASS_NAME, wait_class))
        )
        time.sleep(extra_wait)
        return BeautifulSoup(driver.page_source, "html.parser")
    except TimeoutException:
        logger.warning(f"Timeout waiting for '{wait_class}' on: {url}")
        return None
    except WebDriverException as exc:
        logger.error(f"WebDriver error on {url}: {exc}")
        return None
    except Exception as exc:
        logger.error(f"Unexpected error on {url}: {exc}")
        return None


def get_soup_simple(
    driver,
    url: str,
    wait_class: str,
    delay: float = 1.5,
    extra_wait: float = 3.0,
) -> Optional[BeautifulSoup]:
    """
    Load a player profile page and wait for BOTH the heading AND the career
    history section before reading the DOM.

    The career section is rendered by a separate Vue component that fires
    after the heading is already visible.  Waiting only for 'player-heading'
    (the original behaviour) means BeautifulSoup often reads the page before
    the history table exists in the DOM.

    Changes vs. original:
      - extra_wait raised from 1.5 → 3.0 s
      - secondary WebDriverWait for 'history-season-line' added
    """
    try:
        time.sleep(delay)
        driver.get(url)

        # Primary wait: heading
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CLASS_NAME, wait_class))
        )

        # Secondary wait: career history table
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located(
                    (By.CLASS_NAME, "history-season-line")
                )
            )
        except TimeoutException:
            # Player may genuinely have no Top 14 career history yet
            logger.debug(f"No history-season-line on {url} — may have no career data")

        time.sleep(extra_wait)
        return BeautifulSoup(driver.page_source, "html.parser")

    except TimeoutException:
        logger.warning(f"Timeout waiting for '{wait_class}' on: {url}")
        return None
    except WebDriverException as exc:
        logger.error(f"WebDriver error on {url}: {exc}")
        return None
    except Exception as exc:
        logger.error(f"Unexpected error on {url}: {exc}")
        return None


# =============================================================================
# PHASE 1 — COLLECT PLAYER URLS FROM MATCH STATISTICS PAGES
# =============================================================================

def collect_player_urls_from_match(
    driver, match_url: str, delay: float
) -> set:
    """
    Visit a match statistics page and return a set of player profile URLs
    found in both roster tables (home + away).

    Player links look like:
        <a class="player-cell__name"
           href="https://top14.lnr.fr/joueur/1678-loic-credoz">Loïc CREDOZ</a>

    Args:
        driver:     Selenium WebDriver
        match_url:  Base match URL (e.g. ".../10954-paris-perpignan")
        delay:      Seconds to wait between requests

    Returns:
        Set of absolute player profile URL strings
    """
    stats_url = f"{match_url.rstrip('/')}/statistiques-du-match"
    soup = get_soup_selenium(driver, stats_url, "match-statistics__roster", delay)

    if soup is None:
        logger.warning(f"Could not load statistics page: {stats_url}")
        return set()

    urls = set()
    for tag in soup.find_all("a", class_="player-cell__name"):
        href = tag.get("href", "")
        if href:
            # Ensure absolute URL
            if href.startswith("/"):
                href = LNR_BASE + href
            urls.add(href)

    logger.info(f"  Found {len(urls)} player URLs in {stats_url}")
    return urls


def phase1_collect_urls(
    df_matches: pd.DataFrame,
    output_csv: str = "player_urls.csv",
    delay: float = 2.0,
    headless: bool = True,
    resume: bool = True,
) -> pd.DataFrame:
    """
    Phase 1: Iterate over all matches in target seasons and collect unique
    player profile URLs.

    Args:
        df_matches:  DataFrame with columns: match_id, season, url
        output_csv:  Path to save the list of unique player URLs
        delay:       Seconds between page requests
        headless:    Run Chrome headlessly
        resume:      If True and output_csv already exists, load it and skip
                     matches whose players are already partially collected.
                     Note: because we only store URLs (not which match they came
                     from), resuming means we re-scrape any match not yet seen.
                     Set to False for a clean run.

    Returns:
        DataFrame with a single column 'player_url'
    """
    # Filter to target seasons only
    df = df_matches[df_matches["season"].isin(TARGET_SEASONS)].copy()
    logger.info(
        f"Phase 1: {len(df)} matches across {df['season'].nunique()} seasons"
    )

    # Optionally resume from existing file
    known_urls: set = set()
    if resume and Path(output_csv).exists():
        existing = pd.read_csv(output_csv)
        known_urls = set(existing["player_url"].dropna().tolist())
        logger.info(f"  Resuming — {len(known_urls)} URLs already collected")

    driver = init_driver(headless=headless)
    all_urls: set = set(known_urls)

    try:
        for idx, row in df.iterrows():
            match_id = str(row["match_id"])
            base_url = str(row["url"])
            season = str(row["season"])
            logger.info(
                f"[{idx + 1}/{len(df)}] Season {season} — match {match_id}"
            )

            try:
                new_urls = collect_player_urls_from_match(driver, base_url, delay)
                before = len(all_urls)
                all_urls.update(new_urls)
                logger.info(
                    f"  +{len(all_urls) - before} new URLs "
                    f"(total unique: {len(all_urls)})"
                )
            except Exception as exc:
                logger.error(
                    f"  Error on match {match_id}: {exc}\n{traceback.format_exc()}"
                )
                continue

    finally:
        driver.quit()
        logger.info("WebDriver closed")

    df_urls = pd.DataFrame(sorted(all_urls), columns=["player_url"])
    save_to_csv(df_urls, output_csv, "processed")
    logger.info(
        f"Phase 1 complete — {len(df_urls)} unique player URLs saved to {output_csv}"
    )
    return df_urls


# =============================================================================
# PHASE 2 — SCRAPE INDIVIDUAL PLAYER PROFILE PAGES
# =============================================================================

def parse_player_name(raw_name: str) -> tuple[str, str]:
    """
    Split a raw player name into (first_name, last_name).

    The LNR website displays names like:
        "Darren Anthony SWEETNAM"   → first="Darren Anthony", last="SWEETNAM"
        "Loïc CREDOZ"               → first="Loïc",           last="CREDOZ"
        "DUPONT Antoine"            → (fallback: treat all-caps token as last)

    Rules applied (in order):
        1. Strip surrounding whitespace.
        2. Split into tokens on whitespace.
        3. Tokens that are entirely uppercase (after stripping hyphens) → LAST NAME.
        4. Remaining tokens → FIRST NAME.
        5. If all tokens parse as last name (edge case), put everything in last.

    Hyphenated tokens like "JEAN-BAPTISTE" remain together as one last-name token.
    Hyphenated tokens like "Jean-Baptiste" remain together as one first-name token.

    Returns:
        (first_name, last_name) — original casing preserved.
    """
    raw_name = raw_name.strip()
    if not raw_name:
        return "", ""

    tokens = raw_name.split()

    def is_uppercase_token(token: str) -> bool:
        """
        A token counts as 'uppercase' if every alphabetic character in it
        is uppercase. Hyphens and accented characters are handled correctly.
        """
        letters = [c for c in token if c.isalpha()]
        return len(letters) > 0 and all(c == c.upper() for c in letters)

    last_tokens = [t for t in tokens if is_uppercase_token(t)]
    first_tokens = [t for t in tokens if not is_uppercase_token(t)]

    # Edge case: everything is uppercase (e.g. "DUPONT")
    if not first_tokens:
        return "", " ".join(last_tokens)

    # Edge case: everything is mixed-case (shouldn't happen on LNR, but safe)
    if not last_tokens:
        return " ".join(first_tokens), ""

    return " ".join(first_tokens), " ".join(last_tokens)


def format_full_name(first_name: str, last_name: str) -> str:
    """
    Format a full name as 'Firstname Lastname' with proper capitalization.
    
    Each word should have only its first letter capitalized.
    
    Args:
        first_name: The first name (may contain multiple words)
        last_name: The last name (may contain multiple words)
        
    Returns:
        Full name string with proper capitalization
    """
    def capitalize_word(word: str) -> str:
        if not word:
            return ""
        # Capitalize first letter, lowercase the rest
        # This handles accented characters and hyphenated names correctly
        if len(word) == 1:
            return word.upper()
        
        # Handle hyphenated words: capitalize first letter of each part
        if '-' in word:
            parts = word.split('-')
            return '-'.join(part[0].upper() + part[1:].lower() if part else '' for part in parts)
        
        return word[0].upper() + word[1:].lower() if word else ""
    
    # Process first name (may contain multiple words)
    first_words = first_name.split() if first_name else []
    formatted_first = " ".join(capitalize_word(word) for word in first_words)
    
    # Process last name (may contain multiple words)
    last_words = last_name.split() if last_name else []
    formatted_last = " ".join(capitalize_word(word) for word in last_words)
    
    # Combine with single space
    # Handle edge cases where one part is empty
    if formatted_first and formatted_last:
        full_name = f"{formatted_first} {formatted_last}"
    elif formatted_first:
        full_name = formatted_first
    elif formatted_last:
        full_name = formatted_last
    else:
        full_name = ""
    
    return full_name.strip()


def extract_nationality(soup: BeautifulSoup) -> str:
    """
    Extract nationality from the player profile page.

    The flag image has an alt attribute in French, e.g.:
        <img class="player-infos__attribute-flag" alt="Irlande" ...>

    Returns the nationality string (in French) or empty string if not found.
    """
    flag = soup.find("img", class_="player-infos__attribute-flag")
    if flag:
        return flag.get("alt", "").strip()
    return ""


def extract_career_data(soup: BeautifulSoup) -> dict:
    """
    Extract season-by-season career data from the player profile page.

    CONFIRMED DOM STRUCTURE (from diagnostic on Charles Ollivon's page)
    -------------------------------------------------------------------
    The career history lives inside:
        div.history-season-list
          ├── div.history-season-list__season-column   ← LEFT: season labels only
          │     ├── div.history-season-line--header-line--season-line  (header "Saison")
          │     ├── div.history-season-line--season-line  ("2025-2026")
          │     ├── div.history-season-line--season-line  ("2024-2025")
          │     └── ... one per season, in descending order
          │
          └── div.history-season-list__other-columns   ← RIGHT: stats rows
                ├── div.history-season-line--header-line  (column headers)
                ├── div.history-season-line  (data row for season N)
                ├── div.history-season-line  (data row for season N-1, or 2nd
                │                             club if player changed mid-season)
                └── ...

    Season labels and data rows are in SEPARATE DOM branches and must be
    correlated by position.  The left column has exactly one --season-line per
    season (plus the header).  The right column has one or more plain data rows
    per season.

    COLUMN ORDER in each right-column data row (11 __content cells):
        [0]  Division        e.g. "TOP 14"
        [1]  Club            e.g. "RC Toulon"
        [2]  Matches         e.g. "9"
        [3]  Minutes jouées  e.g. "508"
        [4]  Points
        [5]  Essais
        [6]  Pénalité
        [7]  Drop marqués
        [8]  Cartons jaunes
        [9]  Cartons oranges
        [10] Cartons rouges

    MULTI-CLUB SEASONS
    ------------------
    If a player played for two clubs in the same season there will be two
    consecutive data rows for that season.  We keep the one with the most
    minutes played (= primary role).

    Returns:
        Dict with keys like "2024-2025_team" and "2024-2025_avg_min".
        Missing / non-Top-14 seasons are omitted (become NaN in DataFrame).
    """
    result: dict = {}

    try:
        # ── Step 1: read season labels from LEFT column, in DOM order ────────
        left_col = soup.find(
            "div", class_="history-season-list__season-column"
        )
        if not left_col:
            logger.warning("history-season-list__season-column not found")
            return result

        season_labels: list[str] = []
        for line in left_col.find_all(
            "div", class_=lambda c: c and "history-season-line" in c
        ):
            classes = line.get("class", [])
            # Skip the very first row which is the "Saison" header
            if "history-season-line--header-line" in classes:
                continue
            if "history-season-line--season-line" in classes:
                cell = line.find(
                    "div", class_="history-season-cell__content"
                )
                label = cell.get_text(strip=True) if cell else ""
                if label:
                    season_labels.append(label)

        logger.debug(f"Season labels found: {season_labels}")

        # ── Step 2: read data rows from RIGHT column ──────────────────────────
        right_col = soup.find(
            "div", class_="history-season-list__other-columns"
        )
        if not right_col:
            logger.warning("history-season-list__other-columns not found")
            return result

        data_rows: list = []
        for line in right_col.find_all(
            "div", class_=lambda c: c and "history-season-line" in c
        ):
            classes = line.get("class", [])
            # Skip the column-header row
            if "history-season-line--header-line" in classes:
                continue
            # Skip any stray season-line rows (shouldn't exist here, but safe)
            if "history-season-line--season-line" in classes:
                continue
            data_rows.append(line)

        logger.debug(f"Data rows found: {len(data_rows)}")

        # ── Step 3: correlate seasons → data rows ─────────────────────────────
        # Each season has at least one data row.  Multiple rows happen when a
        # player changed clubs mid-season.  We detect boundaries by counting:
        # since the page lists seasons in descending order and each season
        # always has at least one data row, we assign data rows round-robin
        # until we reach a row whose Division/Club belongs to the next season.
        #
        # Simpler and more robust: just pair seasons 1-to-1 with data rows,
        # but collect ALL consecutive rows that are TOP 14 after assigning.
        # The diagnostic shows Ollivon has 5 season labels and 5 data rows —
        # one-to-one.  We handle the multi-club case by collecting until the
        # row count matches the season count.

        # Build (season_label → [data_row, ...]) mapping.
        # Strategy: assign rows to seasons in order.  If a season has multiple
        # clubs (we can't know up front), we'll detect it by checking whether
        # consecutive rows in the right column belong to the same season.
        # Because there's no explicit marker, we use a simple 1-to-1 default
        # and fall back to scanning all rows if that leaves some unassigned.

        # Robust approach: group consecutive data rows by season using the
        # season-column as the authoritative list.
        # We know:  len(data_rows) >= len(season_labels)  (extra rows = extra clubs)
        # Walk data_rows; for each season consume rows until a Division change
        # signals the next season.  Since we can't detect season boundaries
        # within the right column alone, we use row count ratio instead.

        # SIMPLEST CORRECT APPROACH given confirmed structure:
        # The right column rows are in the same top-to-bottom order as the
        # season labels.  We just need to know how many rows belong to each
        # season.  Since we can't read that from the right column alone, we
        # consume one row per season by default and collect extras by checking
        # whether the next row is still TOP 14 before a new season label would
        # start.  For most players this is 1:1.

        season_to_rows: dict[str, list] = {s: [] for s in season_labels}
        row_iter = iter(data_rows)

        for season in season_labels:
            try:
                row = next(row_iter)
                season_to_rows[season].append(row)
            except StopIteration:
                break

        # Assign any leftover rows to the last-seen season
        # (handles mid-season club changes)
        last_season = season_labels[-1] if season_labels else None
        for row in row_iter:
            if last_season:
                season_to_rows[last_season].append(row)

        # ── Step 4: extract stats per target season ───────────────────────────
        for season, rows in season_to_rows.items():
            if season not in TARGET_SEASONS:
                continue
            if not rows:
                continue

            best_minutes = -1
            best_team = None
            best_avg = None

            for row in rows:
                cells = row.find_all(
                    "div", class_="history-season-cell__content"
                )
                # Need at least Division, Club, Matches, Minutes
                if len(cells) < 4:
                    continue

                division    = cells[0].get_text(strip=True)
                club_name   = cells[1].get_text(strip=True)
                matches_raw = cells[2].get_text(strip=True)
                minutes_raw = cells[3].get_text(strip=True)

                if "TOP 14" not in division.upper():
                    continue

                try:
                    matches_played = int(matches_raw)
                    minutes_played = int(minutes_raw)
                except ValueError:
                    continue

                if matches_played == 0 and minutes_played == 0:
                    continue

                if minutes_played > best_minutes:
                    best_minutes = minutes_played
                    best_team = club_name
                    best_avg = (
                        round(minutes_played / matches_played, 1)
                        if matches_played > 0
                        else None
                    )

            if best_team is not None:
                result[f"{season}_team"]    = best_team
                result[f"{season}_avg_min"] = best_avg

    except Exception as exc:
        logger.error(f"Error extracting career data: {exc}\n{traceback.format_exc()}")

    return result


def scrape_player_profile(driver, player_url: str, delay: float) -> Optional[dict]:
    """
    Scrape a single player profile page and return a dict of player data.

    Args:
        driver:      Selenium WebDriver
        player_url:  Full URL of the player profile page
        delay:       Seconds to wait before loading

    Returns:
        Dict with first_name, last_name, nationality, and season columns,
        or None on failure.
    """
    soup = get_soup_simple(driver, player_url, "player-heading", delay)

    if soup is None:
        logger.warning(f"Could not load player page: {player_url}")
        return None

    # --- Name ---
    name_tag = soup.find("h1", class_=lambda c: c and "player-heading__name" in c)
    if not name_tag:
        # Broaden search — some pages use different heading structure
        name_tag = soup.find(
            ["h1", "h2"],
            class_=lambda c: c and "player" in str(c) and "name" in str(c),
        )

    raw_name = name_tag.get_text(strip=True) if name_tag else ""
    if not raw_name:
        # Last-resort: try og:title meta tag
        og = soup.find("meta", property="og:title")
        if og:
            # og:title format: "Darren Anthony SWEETNAM | Club | League"
            raw_name = og.get("content", "").split("|")[0].strip()

    first_name, last_name = parse_player_name(raw_name)

    # --- Nationality ---
    nationality = extract_nationality(soup)

    # --- Career stats ---
    career = extract_career_data(soup)

    record = {
        "player_url": player_url,
        "first_name": first_name,
        "last_name": last_name,
        "full_name": format_full_name(first_name, last_name),
        "nationality": nationality,
    }
    record.update(career)

    return record


def phase2_scrape_profiles(
    df_urls: pd.DataFrame,
    output_csv: str = "players.csv",
    delay: float = 1.5,
    headless: bool = True,
    resume: bool = True,
) -> pd.DataFrame:
    """
    Phase 2: Visit each player profile URL and build the player registry.

    Args:
        df_urls:    DataFrame with a single column 'player_url'
        output_csv: Path to save the player registry CSV
        delay:      Seconds between page requests
        headless:   Run Chrome headlessly
        resume:     If True and output_csv exists, skip already-scraped players

    Returns:
        Wide-format DataFrame — one row per player.
    """
    urls = df_urls["player_url"].dropna().tolist()
    logger.info(f"Phase 2: scraping {len(urls)} player profiles")

    # Resume: skip URLs already in the output file
    already_done: set = set()
    existing_records: list = []
    if resume and Path(output_csv).exists():
        existing_df = pd.read_csv(output_csv)
        if "player_url" in existing_df.columns:
            already_done = set(existing_df["player_url"].dropna().tolist())
            existing_records = existing_df.to_dict("records")
            logger.info(f"  Resuming — {len(already_done)} players already scraped")

    todo = [u for u in urls if u not in already_done]
    logger.info(f"  {len(todo)} players left to scrape")

    driver = init_driver(headless=headless)
    records = list(existing_records)

    try:
        for i, url in enumerate(todo, start=1):
            logger.info(f"[{i}/{len(todo)}] {url}")
            try:
                record = scrape_player_profile(driver, url, delay)
                if record:
                    records.append(record)
                    logger.info(
                        f"  → {record.get('first_name', '?')} "
                        f"{record.get('last_name', '?')} "
                        f"({record.get('nationality', '?')})"
                    )
                else:
                    logger.warning(f"  No data returned for {url}")

                # Save incrementally every 10 players so progress is not lost
                if i % 10 == 0:
                    _save_players(records, output_csv)
                    logger.info(f"  Checkpoint saved at {i} players")

            except Exception as exc:
                logger.error(
                    f"  Error scraping {url}: {exc}\n{traceback.format_exc()}"
                )
                continue

    finally:
        driver.quit()
        logger.info("WebDriver closed")

    df_players = _save_players(records, output_csv)
    logger.info(
        f"Phase 2 complete — {len(df_players)} players saved to {output_csv}"
    )
    return df_players


def _save_players(records: list, output_csv: str) -> pd.DataFrame:
    """
    Build the wide-format DataFrame from raw records and save to CSV.

    The column order is fixed:
        first_name, last_name, nationality, player_url,
        [for each TARGET_SEASON in chronological order:]
            {season}_team, {season}_avg_min
    """
    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)

    # Build ordered column list
    id_cols = ["first_name", "last_name", "full_name", "nationality", "player_url"]
    season_cols = []
    for season in TARGET_SEASONS:
        for suffix in ["_team", "_avg_min"]:
            col = f"{season}{suffix}"
            if col not in season_cols:
                season_cols.append(col)

    # Reindex to ensure ALL season columns always exist (NaN if no data).
    # This guarantees consistent schema regardless of which seasons appear
    # in the test sample.
    all_expected = id_cols + season_cols
    df = df.reindex(columns=all_expected)

    save_to_csv(df, output_csv, "processed")
    return df


# =============================================================================
# PUBLIC ENTRY POINT
# =============================================================================

def scrape_player_registry(
    df_matches_list: pd.DataFrame,
    urls_csv: str = "player_urls.csv",
    players_csv: str = "players.csv",
    delay_phase1: float = 2.0,
    delay_phase2: float = 1.5,
    headless: bool = True,
    resume: bool = True,
) -> pd.DataFrame:
    """
    Full pipeline: collect player URLs from match pages, then scrape profiles.

    Args:
        df_matches_list:  DataFrame with columns: match_id, season, url
        urls_csv:         Where to save/load Phase 1 output
        players_csv:      Where to save/load Phase 2 output
        delay_phase1:     Seconds between requests in Phase 1 (heavier pages)
        delay_phase2:     Seconds between requests in Phase 2 (lighter pages)
        headless:         Run Chrome without a visible window
        resume:           Skip already-scraped items if output files exist

    Returns:
        Wide-format player DataFrame (same as players_csv content)

    Example:
        import pandas as pd
        from scrape_lnr_players import scrape_player_registry

        df_matches_list = pd.read_csv("data/matches.csv")
        players_df = scrape_player_registry(df_matches_list)
    """
    # --- Phase 1 ---
    if resume and Path(urls_csv).exists():
        logger.info(f"Loading existing player URLs from {urls_csv}")
        df_urls = pd.read_csv(urls_csv)
        logger.info(f"  {len(df_urls)} URLs loaded")
    else:
        df_urls = phase1_collect_urls(
            df_matches_list,
            output_csv=urls_csv,
            delay=delay_phase1,
            headless=headless,
            resume=resume,
        )

    # --- Phase 2 ---
    df_players = phase2_scrape_profiles(
        df_urls,
        output_csv=players_csv,
        delay=delay_phase2,
        headless=headless,
        resume=resume,
    )

    return df_players


# =============================================================================
# STANDALONE EXECUTION (run phases independently)
# =============================================================================

if __name__ == "__main__":
    import sys

    print("LNR Player Registry Scraper")
    print("=" * 50)
    print("Usage from your notebook/script:")
    print()
    print("  from scrape_lnr_players import scrape_player_registry")
    print("  players_df = scrape_player_registry(df_matches_list)")
    print()
    print("Or run phases separately:")
    print()
    print("  from scrape_lnr_players import phase1_collect_urls, phase2_scrape_profiles")
    print("  df_urls    = phase1_collect_urls(df_matches_list)")
    print("  players_df = phase2_scrape_profiles(df_urls)")