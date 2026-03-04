"""
Diagnostic — inspect the compositions page to find player URL anchors.
"""
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

URL = "https://top14.lnr.fr/feuille-de-match/2021-2022/j18/9859-pau-toulouse/compositions"

options = Options()
options.add_argument("--headless")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--window-size=1920,1080")
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

driver.get(URL)
time.sleep(3)
soup = BeautifulSoup(driver.page_source, "html.parser")
driver.quit()
print("Page loaded.\n")

# 1. All anchors linking to /joueur/ — these are player profile URLs
print("=== All <a href='/joueur/...'> links ===")
player_links = soup.find_all('a', href=lambda h: h and '/joueur/' in h)
print(f"Found {len(player_links)} player links")
for a in player_links[:10]:
    print(f"  href='{a.get('href')}'  classes={a.get('class')}  text='{a.get_text(strip=True)[:30]}'")
    # Show parent context
    parent = a.parent
    print(f"    parent: <{parent.name} class={parent.get('class')}>")

# 2. Unique class names containing 'player', 'lineup', 'composition', 'team'
print("\n=== Relevant class names ===")
seen = set()
for tag in soup.find_all(True):
    for cls in tag.get('class', []):
        if any(k in cls.lower() for k in ['player', 'lineup', 'compo', 'team', 'roster', 'squad']):
            if cls not in seen:
                seen.add(cls)
                print(f"  {cls}")

# 3. Show structure around the first player link
print("\n=== Structure around first player link ===")
if player_links:
    a = player_links[0]
    # Walk up 4 levels
    node = a
    chain = []
    for _ in range(5):
        chain.append(f"<{node.name} class={node.get('class')}>")
        node = node.parent
        if not node or not node.name:
            break
    print("  " + " → ".join(reversed(chain)))