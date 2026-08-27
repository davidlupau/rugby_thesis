"""
Utility functions for data loading and saving operations.

This module provides helper functions for:
    - Loading datasets from CSV files
    - Saving DataFrames to CSV files with proper path handling
    - Managing file paths relative to the project root

All paths are resolved relative to the project root directory to ensure
consistent behavior regardless of where the script is executed from.
"""

import pandas as pd
import re
from pathlib import Path
from typing import Optional, Union, Dict


def extract_player_id(player_url: str) -> Optional[str]:
    """
    Extract the canonical numeric player ID from an LNR profile URL.

    LNR serves the same player from multiple domains (e.g. prod2.lnr.fr and
    top14.lnr.fr) with the same numeric ID — dedup must key on this ID, not
    the full URL string, or the same player gets queued/scraped twice.
    """
    match = re.search(r'/joueur/(\d+)-', player_url)
    return match.group(1) if match else None


def load_dataset(folder_name: str, file_name: str) -> pd.DataFrame:
    """
    Load the dataset from a CSV file.

    Args:
        folder_name (str): Name of the subfolder within /data folder
        file_name (str): Name of the CSV file in the specified subfolder

    Returns:
        pd.DataFrame: DataFrame containing the data from the CSV file, or None if error occurs

    Example:
        df = load_dataset("processed", "matches.csv")
        # Loads data/processed/matches.csv
    """
    print("\nLoading dataset...\n")
    try:
        # Get the project root (go up from src/)
        project_root = Path(__file__).parent.parent
        data_file = project_root / "data" / folder_name / file_name

        # Check if file exists first
        if not data_file.exists():
            print(f"File not found: {data_file}")
            return None

        # Read CSV file
        df = pd.read_csv(data_file)
        print(f"Successfully loaded {file_name} from {folder_name}/\n")
        return df
    except Exception as e:
        print(f"Error loading {file_name} from {folder_name}/: {e}")
        return None

def save_to_csv(data: pd.DataFrame, file_name: str, folder_name: str = None) -> Union[str, None]:
    """
    Save analysis results to CSV file(s).

    Can handle both single DataFrames and dictionaries of DataFrames.
    Automatically creates directories if they don't exist.

    Args:
        data: DataFrame or dict of DataFrames to save
        file_name (str): Name of the output file (without extension for dicts)
        folder_name (str, optional): Subfolder within data/ to save to.
                                     If None, saves to data/ root.

    Returns:
        str or list: Path(s) to saved file(s), None if failed

    Example:
        # Save single DataFrame
        save_to_csv(df, "results.csv", "analysis_output")
        
        # Save multiple DataFrames (dict)
        save_to_csv({"train": train_df, "test": test_df}, "datasets", "processed")
    """
    print(f"Saving analysis to {file_name}...\n")
    try:
        # Get the project root (go up from src/)
        project_root = Path(__file__).parent.parent
        
        # Construct output directory path
        if folder_name:
            output_dir = project_root / "data" / folder_name
        else:
            output_dir = project_root / "data"

        # Create directory if it doesn't exist
        output_dir.mkdir(parents=True, exist_ok=True)

        if isinstance(data, dict):
            # Multiple DataFrames - save each as separate CSV file
            saved_files = []
            for sheet_name, df in data.items():
                # Create filename for each DataFrame
                if len(data) == 1:
                    # If only one DataFrame in dict, use the provided file_name
                    csv_file_name = f"{Path(file_name).stem}.csv"
                else:
                    # If multiple DataFrames, append sheet_name to filename
                    base_name = Path(file_name).stem
                    csv_file_name = f"{base_name}_{sheet_name}.csv"
                
                output_file = output_dir / csv_file_name
                df.to_csv(output_file, index=False)
                saved_files.append(str(output_file))
                print(f"  Saved sheet '{sheet_name}' to {csv_file_name}")
            
            print(f"\nSuccessfully saved {len(saved_files)} CSV files to {output_dir}/\n")
            return saved_files if len(saved_files) > 1 else saved_files[0]
        else:
            # Single DataFrame
            # Ensure file has .csv extension
            if not file_name.lower().endswith('.csv'):
                file_name = f"{Path(file_name).stem}.csv"
            
            output_file = output_dir / file_name
            data.to_csv(output_file, index=False)
            
            print(f"Successfully saved to {output_file}\n")
            return str(output_file)

    except Exception as e:
        print(f"Error saving {file_name}: {e}")
        return None
