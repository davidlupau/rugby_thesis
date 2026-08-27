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
except ImportError as e:
    raise ImportError(
        "Selenium is required. Run: pip install selenium webdriver-manager"
    ) from e


# =============================================================================
# CONFIGURATION
# =============================================================================

TARGET_SEASONS = SEASONS


def _resolve_processed_path(filename: str) -> Path:
    """
    Resolve a bare filename (e.g. "players.csv") to its actual location in
    data/processed/, matching where save_to_csv(..., "processed") writes it.
    A path that already has a directory component is returned unchanged.
    """
    path = Path(filename)
    if path.parent != Path('.'):
        return path
    project_root = Path(__file__).parent.parent.parent
    return project_root / "data" / "processed" / filename



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


def _expand_career_history(driver) -> None:
    """
    Click "Afficher les 5 suivants" repeatedly until all seasons are visible.

    KEY FINDINGS FROM DIAGNOSTIC
    -----------------------------
    - The element is a <div class="show-more history-season-list__show-more">
      containing a <span class="show-more__link">.
    - It is displayed=False (off-screen) so Selenium's .click() silently fails.
    - driver.execute_script("arguments[0].click()", el) works correctly.
    - One click adds 5 more seasons. Players with 10+ seasons need 2 clicks.

    We loop until the element is gone from the DOM (no more hidden seasons).
    """
    css = "div.history-season-list__show-more"
    max_clicks = 10  # safety cap
    for _ in range(max_clicks):
        els = driver.find_elements(By.CSS_SELECTOR, css)
        if not els:
            break
        try:
            driver.execute_script("arguments[0].click();", els[0])
            time.sleep(1.5)  # wait for new rows to render
        except Exception as exc:
            logger.debug(f"_expand_career_history click failed: {exc}")
            break


def get_soup_simple(
    driver,
    url: str,
    wait_class: str,
    delay: float = 1.5,
    extra_wait: float = 2.0,
) -> Optional[BeautifulSoup]:
    """
    Load a player profile page, expand ALL hidden career seasons, then return
    BeautifulSoup over the fully-rendered DOM.

    Changes vs. original:
      - Secondary WebDriverWait for 'history-season-line' (career section
        loads after the heading via a separate Vue component).
      - _expand_career_history() JS-clicks "Afficher les 5 suivants" until
        all seasons are visible before reading page source.
    """
    try:
        time.sleep(delay)
        driver.get(url)

        # Wait for player heading
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CLASS_NAME, wait_class))
        )

        # Wait for career history table
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located(
                    (By.CLASS_NAME, "history-season-line")
                )
            )
        except TimeoutException:
            logger.debug(f"No history-season-line on {url} — player may have no career data")

        # Expand hidden seasons
        _expand_career_history(driver)

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
    # seen_by_id maps canonical numeric player ID -> the URL kept for it,
    # so the same player found under a different domain isn't re-queued.
    seen_by_id: dict = {}
    if resume and _resolve_processed_path(output_csv).exists():
        existing = pd.read_csv(_resolve_processed_path(output_csv))
        for url in existing["player_url"].dropna().tolist():
            pid = extract_player_id(url)
            if pid and pid not in seen_by_id:
                seen_by_id[pid] = url
        logger.info(f"  Resuming — {len(seen_by_id)} players already collected")

    driver = init_driver(headless=headless)

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
                before = len(seen_by_id)
                for url in new_urls:
                    pid = extract_player_id(url)
                    if pid and pid not in seen_by_id:
                        seen_by_id[pid] = url
                logger.info(
                    f"  +{len(seen_by_id) - before} new players "
                    f"(total unique: {len(seen_by_id)})"
                )
            except Exception as exc:
                logger.error(
                    f"  Error on match {match_id}: {exc}\n{traceback.format_exc()}"
                )
                continue

    finally:
        driver.quit()
        logger.info("WebDriver closed")

    df_urls = pd.DataFrame(sorted(seen_by_id.values()), columns=["player_url"])
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

    CONFIRMED DOM STRUCTURE
    -----------------------
    div.history-season-list
      ├── div.history-season-list__season-column    ← LEFT: season labels only
      │     ├── div.--header-line.--season-line     ("Saison" header)
      │     ├── div.--season-line                   ("2025-2026")
      │     ├── div.--season-line                   ("2024-2025")
      │     └── ...  one per season, newest first
      │
      └── div.history-season-list__other-columns    ← RIGHT: stats rows
            ├── div.--header-line                   (column headers)
            ├── div.history-season-line             (data row for season 0)
            ├── div.history-season-line             (data row for season 1)
            └── ...

    Season labels (left) and data rows (right) are in SEPARATE DOM branches
    correlated by position: label[0] → row[0], label[1] → row[1], …

    Data row __content cell order (confirmed, 11 cells):
        [0] Division  [1] Club  [2] Matches  [3] Minutes jouées  [4] Points …

    MULTI-CLUB: two data rows for same season → keep the one with most minutes.
    PAGINATION: _expand_career_history() has already clicked "Afficher les 5
                suivants" before this runs, so all seasons are in the DOM.

    Returns dict with "{season}_team" / "{season}_avg_min" for target seasons.
    """
    result: dict = {}

    try:
        # ── Left column: ordered season labels ───────────────────────────────
        left_col = soup.find("div", class_="history-season-list__season-column")
        if not left_col:
            logger.warning("history-season-list__season-column not found")
            return result

        season_labels: list[str] = []
        for line in left_col.find_all(
            "div", class_=lambda c: c and "history-season-line" in c
        ):
            classes = line.get("class", [])
            if "history-season-line--header-line" in classes:
                continue
            if "history-season-line--season-line" in classes:
                cell = line.find("div", class_="history-season-cell__content")
                label = cell.get_text(strip=True) if cell else ""
                if label:
                    season_labels.append(label)

        logger.debug(f"Season labels: {season_labels}")

        # ── Right column: plain data rows ─────────────────────────────────────
        right_col = soup.find("div", class_="history-season-list__other-columns")
        if not right_col:
            logger.warning("history-season-list__other-columns not found")
            return result

        data_rows: list = []
        for line in right_col.find_all(
            "div", class_=lambda c: c and "history-season-line" in c
        ):
            classes = line.get("class", [])
            if "history-season-line--header-line" in classes:
                continue
            if "history-season-line--season-line" in classes:
                continue
            data_rows.append(line)

        logger.debug(f"Data rows: {len(data_rows)}")

        # ── Pair seasons → data rows (1-to-1; extras → last season) ──────────
        season_to_rows: dict[str, list] = {s: [] for s in season_labels}
        row_iter = iter(data_rows)
        for season in season_labels:
            try:
                season_to_rows[season].append(next(row_iter))
            except StopIteration:
                break
        last_season = season_labels[-1] if season_labels else None
        for leftover in row_iter:
            if last_season:
                season_to_rows[last_season].append(leftover)

        # ── Extract stats for target seasons ──────────────────────────────────
        for season, rows in season_to_rows.items():
            if season not in TARGET_SEASONS or not rows:
                continue

            best_minutes = -1
            best_team = None
            best_avg = None

            for row in rows:
                cells = row.find_all("div", class_="history-season-cell__content")
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
                        if matches_played > 0 else None
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


MANUAL_REVIEW_THRESHOLD = 3  # fail this many times on the same URL -> flag for manual inspection


def phase2_scrape_profiles(
    df_urls: pd.DataFrame,
    output_csv: str = "players.csv",
    incomplete_csv: str = "players_incomplete.csv",
    delay: float = 1.5,
    headless: bool = True,
    resume: bool = True,
) -> pd.DataFrame:
    """
    Phase 2: Visit each player profile URL and build the player registry.

    Args:
        df_urls:        DataFrame with a single column 'player_url'
        output_csv:      Path to save the player registry CSV
        incomplete_csv:  Path to the persistent failure-tracking CSV (player_url,
                         player_id, fail_count, status). Failures accumulate a
                         fail_count across calls; a URL that keeps failing past
                         MANUAL_REVIEW_THRESHOLD attempts is flagged
                         "manual_review_needed" instead of "timeout", since a
                         repeated failure on one specific page suggests something
                         structurally different rather than a random network blip.
        delay:      Seconds between page requests
        headless:   Run Chrome headlessly
        resume:     If True and output_csv exists, skip already-scraped players

    Returns:
        Wide-format DataFrame — one row per player.
    """
    urls = df_urls["player_url"].dropna().tolist()
    logger.info(f"Phase 2: scraping {len(urls)} player profiles")

    # Resume: skip URLs already in the output file (matched by canonical
    # player ID, since the same player can appear under a different domain)
    already_done_ids: set = set()
    existing_records: list = []
    if resume and _resolve_processed_path(output_csv).exists():
        existing_df = pd.read_csv(_resolve_processed_path(output_csv))
        if "player_url" in existing_df.columns:
            already_done_ids = {
                extract_player_id(u) for u in existing_df["player_url"].dropna()
            }
            already_done_ids.discard(None)
            existing_records = existing_df.to_dict("records")
            logger.info(f"  Resuming — {len(already_done_ids)} players already scraped")

    # Prior fail counts, keyed by player_id, carried over from earlier runs
    fail_counts: dict = {}
    incomplete_path = _resolve_processed_path(incomplete_csv)
    if incomplete_path.exists():
        existing_incomplete = pd.read_csv(incomplete_path)
        for _, r in existing_incomplete.iterrows():
            fail_counts[str(r["player_id"])] = int(r["fail_count"])

    todo = [u for u in urls if extract_player_id(u) not in already_done_ids]
    logger.info(f"  {len(todo)} players left to scrape")

    driver = init_driver(headless=headless)
    records = list(existing_records)

    try:
        for i, url in enumerate(todo, start=1):
            logger.info(f"[{i}/{len(todo)}] {url}")
            pid = extract_player_id(url)
            try:
                record = scrape_player_profile(driver, url, delay)
                if record:
                    records.append(record)
                    fail_counts.pop(pid, None)
                    logger.info(
                        f"  → {record.get('first_name', '?')} "
                        f"{record.get('last_name', '?')} "
                        f"({record.get('nationality', '?')})"
                    )
                else:
                    fail_counts[pid] = fail_counts.get(pid, 0) + 1
                    logger.warning(
                        f"  No data returned for {url} "
                        f"(fail_count={fail_counts[pid]})"
                    )

                # Save incrementally every 10 players so progress is not lost
                if i % 10 == 0:
                    _save_players(records, output_csv)
                    logger.info(f"  Checkpoint saved at {i} players")

            except Exception as exc:
                fail_counts[pid] = fail_counts.get(pid, 0) + 1
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

    # Persist remaining failures so future retries build on this instead of
    # re-deriving fail counts by hand each time.
    url_by_pid = {extract_player_id(u): u for u in urls}
    incomplete_records = []
    manual_review_urls = []
    for pid, count in fail_counts.items():
        status = "manual_review_needed" if count >= MANUAL_REVIEW_THRESHOLD else "timeout"
        if status == "manual_review_needed":
            manual_review_urls.append(url_by_pid.get(pid, pid))
        incomplete_records.append({
            "player_url":  url_by_pid.get(pid, ""),
            "player_id":   pid,
            "fail_count":  count,
            "status":      status,
        })
    df_incomplete = pd.DataFrame(
        incomplete_records, columns=["player_url", "player_id", "fail_count", "status"]
    )
    save_to_csv(df_incomplete, incomplete_csv, "processed")
    logger.info(f"  {len(df_incomplete)} players still failing, saved to {incomplete_csv}")
    if manual_review_urls:
        logger.warning(
            f"⚠️  {len(manual_review_urls)} player(s) failed "
            f"{MANUAL_REVIEW_THRESHOLD}+ times — needs manual inspection: "
            f"{manual_review_urls}"
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
    if resume and _resolve_processed_path(urls_csv).exists():
        logger.info(f"Loading existing player URLs from {urls_csv}")
        df_urls = pd.read_csv(_resolve_processed_path(urls_csv))
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