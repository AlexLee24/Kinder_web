
import sys
import os

# Add app directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'app')))

from app.modules.postgres_database import get_db_connection
import psycopg2.extras

def check_photometry_data():
    try:
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            
            print("Checking photometry table schema...")
            cur.execute("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = 'photometry' AND column_name = 'magnitude';
            """)
            schema = cur.fetchone()
            print(f"Magnitude column type: {schema['data_type']}")
            
            print("\nChecking for non-numeric magnitude values...")
            
            cur.execute("SELECT object_name, magnitude, filter FROM photometry LIMIT 20")
            rows = cur.fetchall()
            
            print(f"Sample data ({len(rows)} rows):")
            
            min_mag = float('inf')
            
            for row in rows:
                print(f"Object: {row['object_name']}, Mag: {row['magnitude']}, Type: {type(row['magnitude'])}")
                
                try:
                    mag_val = row['magnitude']
                    # Handle string magnitudes (e.g. ">19.5")
                    if isinstance(mag_val, str):
                        # Skip upper limits
                        if '>' in mag_val:
                            print("  -> Found '>' in string, skipping")
                            continue
                        val = float(mag_val)
                    # Handle float magnitudes that might be stored as float but we want to be safe
                    elif isinstance(mag_val, (int, float)):
                        val = float(mag_val)
                    else:
                        # Try to convert anything else to string first then check
                        str_val = str(mag_val)
                        if '>' in str_val:
                            print("  -> Found '>' in converted string, skipping")
                            continue
                        val = float(str_val)
                        
                    if val < min_mag:
                        print(f"  -> New min mag: {val} (was {min_mag})")
                        min_mag = val
                        brightest_filter = row['filter']
                except (ValueError, TypeError) as e:
                    print(f"  -> Caught exception: {e}")
                    continue
                except Exception as e:
                    print(f"  -> UNCAUGHT EXCEPTION: {e}")


            cur.close()
        
    except Exception as e:
        print(f"Database error: {e}")

if __name__ == "__main__":
    check_photometry_data()
