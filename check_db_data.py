
import sys
import os

# Add app directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'app')))

from app.modules.postgres_database import get_db_connection
import psycopg2.extras

def check_photometry_data():
    try:
        conn = get_db_connection()
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
        # This query might fail if magnitude is DOUBLE PRECISION and we try to cast to text to check for '>'
        # But if it is TEXT, we can check.
        
        cur.execute("SELECT object_name, magnitude FROM photometry LIMIT 20")
        rows = cur.fetchall()
        
        print(f"Sample data ({len(rows)} rows):")
        for row in rows:
            print(f"Object: {row['object_name']}, Mag: {row['magnitude']}, Type: {type(row['magnitude'])}")
            
            # Check if any value causes the error logic to fail
            mag_val = row['magnitude']
            try:
                if isinstance(mag_val, str):
                    if '>' in mag_val:
                        print("  -> Found '>' in string")
                    else:
                        print("  -> String without '>'")
                elif isinstance(mag_val, (int, float)):
                    print("  -> Numeric type")
                else:
                    print(f"  -> Other type: {type(mag_val)}")
            except Exception as e:
                print(f"  -> ERROR in logic: {e}")

        cur.close()
        conn.close()
        
    except Exception as e:
        print(f"Database error: {e}")

if __name__ == "__main__":
    check_photometry_data()
