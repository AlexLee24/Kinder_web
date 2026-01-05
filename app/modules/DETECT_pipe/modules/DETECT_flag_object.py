import os
import pathlib
import pandas as pd
import glob

# ---- User settings ----
BASE_DIR = pathlib.Path("./")
TNS_DIR = pathlib.Path("./data/tns_daily")
FLAG_DIR = pathlib.Path("./flag")
FLAG_DIR.mkdir(parents=True, exist_ok=True)
FLAG_FILE = FLAG_DIR / "Flag_Object_List.csv"

FLAG_TXT = BASE_DIR / "Flag_objects.txt"

def extract_flag_objects(year=2025):
    # Read flag object list from txt file
    if not FLAG_TXT.exists():
        print(f"Error: {FLAG_TXT} not found")
        return
    
    with open(FLAG_TXT, 'r') as f:
        Flag_Object_List = [line.strip() for line in f if line.strip()]
    
    if not Flag_Object_List:
        # Clear the flag file but keep header
        if FLAG_FILE.exists():
            try:
                existing_df = pd.read_csv(FLAG_FILE)
            except pd.errors.EmptyDataError:
                existing_df = pd.DataFrame()
            if len(existing_df) > 0 and 'Name' in existing_df.columns:
                # Create empty dataframe with same columns
                empty_df = pd.DataFrame(columns=existing_df.columns)
                empty_df.to_csv(FLAG_FILE, index=False)
                print(f"Cleared all objects from {FLAG_FILE}")
            else:
                pd.DataFrame().to_csv(FLAG_FILE, index=False)
        return
    
    print(f"Loaded {len(Flag_Object_List)} object(s) from {FLAG_TXT}")
    
    # First, clean up existing Flag_Object_List.csv
    if FLAG_FILE.exists():
        try:
            flag_df = pd.read_csv(FLAG_FILE)
        except pd.errors.EmptyDataError:
            flag_df = pd.DataFrame()
        
        if len(flag_df) > 0 and 'Name' in flag_df.columns:
            original_count = len(flag_df)
            
            # Keep only rows where Name matches pattern "prefix + space + obj_name"
            def is_in_flag_list(name):
                if pd.isna(name):
                    return False
                name_str = str(name)
                for obj_name in Flag_Object_List:
                    if name_str.endswith(f" {obj_name}"):
                        return True
                return False
            
            mask = flag_df['Name'].apply(is_in_flag_list)
            cleaned_df = flag_df[mask]
            removed_count = original_count - len(cleaned_df)
            
            if removed_count > 0:
                cleaned_df.to_csv(FLAG_FILE, index=False)
                print(f"Removed {removed_count} object(s) not in Flag_Object_List from existing file")
    
    # Get all CSV files in TNS_DIR for specified year
    year_pattern = f"{year}_*" if year else "**"
    csv_files = glob.glob(str(TNS_DIR / year_pattern / "*.csv"), recursive=False)
    csv_files = [f for f in csv_files if not f.endswith("Flag_Object_List.csv")]
    
    if not csv_files:
        print(f"Error: No CSV files found in TNS_DIR for year {year}")
        return
    
    print(f"Found {len(csv_files)} CSV file(s) to search for year {year}")
    
    # Collect matching rows
    all_matches = []
    
    for csv_file in csv_files:
        try:
            df = pd.read_csv(csv_file)
            
            # Strip quotes and normalize column names to lowercase
            df.columns = df.columns.str.strip().str.replace('"', '').str.lower()
            
            # Remove duplicate rows
            df = df.drop_duplicates()
            
            # Check if 'name' column exists
            if 'name' not in df.columns:
                print(f"Warning: 'name' column not found in {os.path.basename(csv_file)}")
                continue
            
            # Search for each flag object
            for obj_name in Flag_Object_List:
                # Match pattern: name ends with obj_name (e.g., "2025akqg")
                mask = df['name'].astype(str).str.endswith(obj_name, na=False)
                matches = df[mask]
                
                if not matches.empty:
                    all_matches.append(matches)
        
        except Exception as e:
            print(f"Error reading {csv_file}: {e}")
    
    # Combine all matches
    if all_matches:
        combined_df = pd.concat(all_matches, ignore_index=True)
        combined_df.drop_duplicates(inplace=True)
        
        # Merge with existing data if FLAG_FILE exists
        if FLAG_FILE.exists():
            try:
                existing_df = pd.read_csv(FLAG_FILE)
                if len(existing_df) > 0:
                    combined_df = pd.concat([existing_df, combined_df], ignore_index=True)
                    combined_df.drop_duplicates(inplace=True)
            except pd.errors.EmptyDataError:
                # File is empty, just use new data
                pass
        
        # Save to Flag_Object_List.csv
        combined_df.to_csv(FLAG_FILE, index=False)
        print(f"\nSaved {len(combined_df)} record(s) to {FLAG_FILE}")
    else:
        print("\nNo matches found")

if __name__ == "__main__":
    extract_flag_objects()

