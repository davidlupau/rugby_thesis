"""
Data collection and preparation pipeline.
Run this ONCE before starting ML analysis.
Creates: data/final/top14_complete.csv
"""
from src.collection.scrape_lnr import scrape_all_seasons
from src.processing.assemble_final_dataset import assemble_final_dataset

def main():
    # Your orchestration code
    pass

if __name__ == "__main__":
    main()