import requests
import pandas as pd
from bs4 import BeautifulSoup
import time
from pathlib import Path
from typing import Callable, Set

# Importing the project utility function.
# This file is src/collection/scrape_wikipedia.py and utils.py is src/utils.py,
# so we add the src/ directory (two levels up) to sys.path — same pattern as
# scrape_lnr.py.
import sys
sys.path.append(str(Path(__file__).parent.parent))
from utils import save_to_csv

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

# Rows in the squad tables whose first cell holds one of these are staff /
# section markers, not players.
_NON_PLAYER_MARKERS = (
    "Replacements:", "Substitutes:", "Coach", "Head coach", "Manager",
)


# =============================================================================
# Parsers — Wikipedia does not use one consistent layout across competitions
# =============================================================================

def parse_squad_tables(soup: BeautifulSoup) -> Set[str]:
    """
    Parse the flat squad tables used on the dedicated ``..._squads`` pages
    (Six Nations, Rugby World Cup) and embedded on the main tournament page
    for the Rugby Championship and the Pacific Nations Cup.

    Table shape (one per national squad, plus "subsequent call-ups" tables):

        Player | Position | Date of birth (age) | Caps | Club/province

    Every player listed — including uncapped and non-playing squad members —
    is returned, which is what we want: a player in camp is unavailable to
    their club whether or not they take the field.
    """
    players: Set[str] = set()

    for table in soup.find_all('table', class_='wikitable'):
        header_row = table.find('tr')
        if not header_row:
            continue
        headers = [c.get_text(' ', strip=True)
                   for c in header_row.find_all(['th', 'td'])]
        if (len(headers) < 3
                or headers[0] != 'Player'
                or headers[1] != 'Position'
                or 'Date of birth' not in headers[2]):
            continue

        for row in table.find_all('tr')[1:]:
            cells = row.find_all(['td', 'th'])
            if len(cells) < 2:
                continue
            name_cell = cells[0]
            if any(marker in name_cell.get_text() for marker in _NON_PLAYER_MARKERS):
                continue

            a_tag = name_cell.find('a')
            name = (a_tag.get_text() if a_tag else name_cell.get_text())
            name = name.split('(')[0].strip().rstrip('*').strip()
            if name:
                players.add(name)

    return players


def parse_match_lineups(soup: BeautifulSoup) -> Set[str]:
    """
    Parse the per-match starting XV / replacement lineups embedded directly on
    a tournament page as side-by-side ``<td style="width:50%">`` columns, each
    wrapping a small table whose rows are ``Position | Number | Player``.

    Used for the End-of-Year Internationals pages, which have no squad tables
    at all — only match lineups.

    NOTE: Wikipedia publishes no ``..._squads`` page for this competition type
    (all such URLs 404; ``Autumn_Nations_Series`` redirects to the same
    lineup-only page), so Autumn Internationals call-up counts are matchday-only
    and are likely undercounted relative to the other four windows (Six
    Nations, Rugby Championship, World Cup, Pacific Cup), where full squad
    tables are available. A player named to an autumn squad but never in a
    matchday 23 will be missed here.
    """
    players: Set[str] = set()

    lineup_columns = soup.find_all(
        'td', style=lambda v: v and 'width:50%' in v.replace(' ', '')
    )
    for col in lineup_columns:
        lineup_table = col.find('table')
        if not lineup_table:
            continue

        for row in lineup_table.find_all('tr'):
            cols = row.find_all('td')
            if len(cols) < 3:
                continue
            name_cell = cols[2]
            if any(marker in name_cell.text for marker in _NON_PLAYER_MARKERS):
                continue

            a_tag = name_cell.find('a')
            name = (a_tag.get_text().strip() if a_tag
                    else name_cell.get_text().split('(')[0].strip())
            if name:
                players.add(name)

    return players


# =============================================================================
# Competition -> parser dispatch
# =============================================================================

# Keyed on a normalised (lower-cased, stripped) competition name.
_PARSER_BY_COMPETITION: dict[str, Callable[[BeautifulSoup], Set[str]]] = {
    '6 nations': parse_squad_tables,
    'six nations': parse_squad_tables,
    'world cup': parse_squad_tables,
    'rugby championship': parse_squad_tables,
    'pacific cup': parse_squad_tables,
    'end of year internationals': parse_match_lineups,
}


def _normalise(competition: str) -> str:
    return str(competition).strip().lower()


def _ensure_squads_url(url: str, competition: str) -> str:
    """
    Six Nations rows historically pointed at the tournament overview page
    (``2024_Six_Nations_Championship``), where the squads do not live. The
    squads are on ``2024_Six_Nations_Championship_squads``. Fix the URL in
    case international_windows.csv has not been updated.
    """
    if _normalise(competition) in ('6 nations', 'six nations'):
        if 'Six_Nations_Championship' in url and not url.endswith('_squads'):
            return url.rstrip('/') + '_squads'
    return url


def get_players_from_wiki(url: str, competition: str) -> Set[str]:
    """
    Fetch a Wikipedia page and extract player names using the parser that
    matches the competition's page layout. Falls back to the other parser if
    the primary one finds nothing (layouts change between years).
    """
    url = _ensure_squads_url(url, competition)
    primary = _PARSER_BY_COMPETITION.get(_normalise(competition), parse_squad_tables)
    fallback = (parse_match_lineups if primary is parse_squad_tables
                else parse_squad_tables)

    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code != 200:
            print(f"  HTTP {response.status_code} for {url}")
            return set()

        soup = BeautifulSoup(response.content, 'html.parser')

        players = primary(soup)
        if not players:
            players = fallback(soup)
            if players:
                print(f"  (primary parser empty, used fallback for {competition})")
        return players
    except Exception as e:
        print(f"Error scraping {url}: {e}")
        return set()


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
        competition = row['competition']

        if pd.isna(url) or 'wiki' not in str(url):
            continue

        print(f"Processing {window_id} ({season}, {competition})...")
        player_names = get_players_from_wiki(url, competition)
        print(f"  -> {len(player_names)} players")

        for name in player_names:
            all_records.append({
                'player_name': name,
                'int_window_id': window_id,
                'season': season,
                'competition': competition
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
