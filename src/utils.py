import pandas as pd
from pathlib import Path


def load_dataset(folder_name, file_name):
    """Load the dataset from a CSV file
    
    Parameters:
        folder_name (string): name of the subfolder within /data folder
        file_name (string): name of the CSV file in the specified subfolder
    
    Returns:
        dataframe containing the data from the CSV file or None if error occurs
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

def save_analysis_to_csv(data, file_name, folder_name=None):
    """Save analysis results to CSV file(s) in analysis_output folder
    
    Parameters:
        data: DataFrame or dict of DataFrames to save
        file_name (str): name of the output file (without extension for dicts)
        folder_name (str, optional): subfolder within analysis_output to save to
    
    Returns:
        str or list: path(s) to saved file(s), None if failed
    """
    print(f"Saving analysis to {file_name}...\n")
    try:
        # Get the project root (go up from src/)
        project_root = Path(__file__).parent.parent
        
        # Construct output directory path
        if folder_name:
            output_dir = project_root / "data" / "analysis_output" / folder_name
        else:
            output_dir = project_root / "data" / "analysis_output"

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
