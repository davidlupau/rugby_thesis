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
    first_name, last_name, nationality,
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

import pandas as pd
from bs4 import BeautifulSoup

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

TARGET_SEASONS = [
    "2017-2018",
    "2018-2019",
    "2021-2022",
    "2022-2023",
    "2023-2024",
    "2024-2025",
]

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
    extra_wait: float = 1.5,
) -> Optional[BeautifulSoup]:
    """
    Same as get_soup_selenium but with shorter waits — used for player profile
    pages that are lighter than the statistics pages.
    """
    return get_soup_selenium(driver, url, wait_class, delay, extra_wait)


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
    df_urls.to_csv(output_csv, index=False)
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

    The career section contains a table of history lines, each with:
        - Season label  (e.g. "2024-2025")
        - Club name     (e.g. "Oyonnax Rugby")
        - Matches played
        - Minutes played

    We compute avg_min = round(minutes / matches, 1) per season.

    Only seasons in TARGET_SEASONS are returned.

    Returns:
        Dict with keys like "2024-2025_team" and "2024-2025_avg_min".
        Missing seasons are not included (will become NaN in the DataFrame).
    """
    result = {}

    try:
        # Each season row has class 'history-season-line'
        # We skip the header line (history-season-line--header-line)
        season_lines = soup.find_all(
            "div",
            class_=lambda c: c and "history-season-line" in c
            and "header" not in c,
        )

        for line in season_lines:
            # --- Season label ---
            # The season pill/button contains the season text, e.g. "2024-2025"
            season_label = None

            # Try the season-cell first
            season_cell = line.find("div", class_="history-season-cell")
            if season_cell:
                text = season_cell.get_text(strip=True)
                # Season labels look like "2024-2025"
                match = re.search(r"\d{4}-\d{4}", text)
                if match:
                    season_label = match.group()

            if not season_label or season_label not in TARGET_SEASONS:
                continue

            # --- Club name ---
            club_name = ""
            club_cell = line.find("a", class_="club-cell__name")
            if not club_cell:
                # Fallback: any element with club-cell__name
                club_cell = line.find(class_="club-cell__name")
            if club_cell:
                club_name = club_cell.get_text(strip=True)

            # --- Matches and minutes ---
            # history-season-cell elements contain individual stat values
            # The order (from the screenshot) is:
            #   [0] season (already parsed above via history-season-cell)
            #   Then in history-season-list__other-columns:
            #     club | matches | minutes | points | tries | penalty | drop |
            #     yellow | orange | red
            # We find all history-season-cell elements inside the line
            cells = line.find_all("div", class_="history-season-cell")
            # Remove the season cell itself; remaining cells hold stats
            # The first cell after the season cell is matches, second is minutes
            # (based on screenshot column order: Matches, Minutes jouées)
            stat_cells = [
                c for c in cells
                if not re.search(r"\d{4}-\d{4}", c.get_text(strip=True))
            ]

            matches_played = None
            minutes_played = None

            if len(stat_cells) >= 2:
                try:
                    matches_played = int(stat_cells[0].get_text(strip=True))
                except ValueError:
                    pass
                try:
                    minutes_played = int(stat_cells[1].get_text(strip=True))
                except ValueError:
                    pass

            # Compute average minutes per match
            avg_min = None
            if matches_played and minutes_played and matches_played > 0:
                avg_min = round(minutes_played / matches_played, 1)

            result[f"{season_label}_team"] = club_name
            result[f"{season_label}_avg_min"] = avg_min

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

                # Save incrementally every 50 players so progress is not lost
                if i % 50 == 0:
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
    id_cols = ["first_name", "last_name", "nationality", "player_url"]
    season_cols = []
    for season in TARGET_SEASONS:
        for suffix in ["_team", "_avg_min"]:
            col = f"{season}{suffix}"
            if col not in season_cols:
                season_cols.append(col)

    # Keep only columns that exist in df
    ordered = [c for c in id_cols + season_cols if c in df.columns]
    # Append any unexpected extra columns at the end
    extra = [c for c in df.columns if c not in ordered]
    df = df[ordered + extra]

    df.to_csv(output_csv, index=False, encoding="utf-8-sig")
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
