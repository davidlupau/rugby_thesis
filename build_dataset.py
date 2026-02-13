import pandas as pd
from src.collection.scrape_matches_list import scrape_matches_list

def main():
    
    # Scrape the list of matches from LNR website
    df_matches_list = scrape_matches_list()



if __name__ == "__main__":
    main()