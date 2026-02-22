import importlib
import scrape_lnr_players
importlib.reload(scrape_lnr_players)

from scrape_lnr_players import scrape_player_profile, init_driver

driver = init_driver(headless=False)
result = scrape_player_profile(
    driver,
    "https://top14.lnr.fr/joueur/1662-darren-anthony-sweetnam",
    delay=2
)
driver.quit()
print(result)