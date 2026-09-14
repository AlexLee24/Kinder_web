import os
from pathlib import Path
import psycopg2
from dotenv import load_dotenv


# ---- Dynamic Env & Config Loader ----

def _load_environmental_variables():
    """Dynamically locates the true project root and loads the correct env file."""
    # __file__ is root/function/database/__init__.py
    # .parent.parent.parent safely reaches 'root'
    project_root = Path(__file__).resolve().parent.parent.parent

    env_path = project_root / ".env"
    detect_env_path = project_root / "detect.env"

    # Use .env first (user preference), fallback to detect.env
    if env_path.exists():
        load_dotenv(str(env_path))
    elif detect_env_path.exists():
        load_dotenv(str(detect_env_path))


def _get_db_config() -> dict:
    """Ensures environment variables are fresh and returns the connection dict."""
    _load_environmental_variables()

    return {
        "host": os.getenv("PG_HOST", "127.0.0.1"),
        "database": os.getenv("PG_DATABASE", "Kinder"),
        "user": os.getenv("PG_USER", "postgres"),
        "password": os.getenv("PG_PASSWORD", ""),
        "port": os.getenv("PG_PORT", "5432"),
        "application_name": "DETECT",
        "connect_timeout": 10,
        "sslmode": "disable",
    }


# ---- Core Connection Functions ----

def get_db_connection():
    """Establish and return a PostgreSQL database connection."""
    try:
        config = _get_db_config()
        conn = psycopg2.connect(**config)
        return conn
    except Exception as e:
        print("Failed to connect to the database:")
        print(e)
        raise


def check_db_connection() -> bool:
    try:
        config = _get_db_config()
        conn = psycopg2.connect(**config)
        conn.close()
        return True
    except Exception:
        return False


# ---- Database Initialization Schema ----

def _ensure_extra_tables():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        DO $$ BEGIN
            BEGIN
                ALTER TABLE transient.photometry
                    ADD CONSTRAINT phot_uniq UNIQUE (obj_id, "MJD", filter, source);
            EXCEPTION WHEN duplicate_table THEN NULL;
            END;
        END $$
        """
    )
    cur.execute(
        """
        ALTER TABLE transient.objects
            ADD COLUMN IF NOT EXISTS kinder_id BIGINT
        """
    )
    cur.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS objects_kinder_id_idx
            ON transient.objects (kinder_id)
            WHERE kinder_id IS NOT NULL
        """
    )
    cur.execute(
        """
        ALTER TABLE transient.cross_matches
            ADD COLUMN IF NOT EXISTS note TEXT
        """
    )
    cur.execute(
        """
        ALTER TABLE transient.cross_matches
            ADD COLUMN IF NOT EXISTS run_date TIMESTAMPTZ DEFAULT now()
        """
    )
    cur.execute(
        """
        ALTER TABLE transient.cross_matches
            ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'Success'
        """
    )
    cur.execute(
        """
        ALTER TABLE transient.cross_matches
            ADD COLUMN IF NOT EXISTS error_message TEXT
        """
    )
    cur.execute(
        """
        ALTER TABLE transient.cross_matches
            ADD COLUMN IF NOT EXISTS flag BOOLEAN DEFAULT FALSE
        """
    )
    cur.execute(
        """
        ALTER TABLE transient.cross_matches
            ADD COLUMN IF NOT EXISTS match_data JSONB
        """
    )
    conn.commit()
    cur.close()
    conn.close()


def init_tns_database() -> bool:
    try:
        _ensure_extra_tables()
        return True
    except Exception as e:
        print("init_tns_database failed:", e)
        return False


# ---- Domain Service Imports & Facades ----

from function.database.fetch_data import DataFetcher
from function.database.upload_data import DataUploader
from function.database.catalogue import CatalogueService


def get_cross_match_results(limit: int = 1000, date: str | None = None) -> list:
    return DataFetcher.get_cross_match_results(limit=limit, date=date)


def get_flagged_objects() -> list[list]:
    return DataFetcher.get_flagged_objects()


def get_target_image(target_name: str) -> bytes | None:
    return DataFetcher.get_target_image(target_name)


def save_flag_objects(flag_list: list):
    DataUploader.save_flag_objects(flag_list)


def save_cross_match_results(results_list: list):
    DataUploader.save_cross_match_results(results_list)


def save_target_image(target_name: str, image_data: bytes, source: str = "DESI") -> bool:
    return DataUploader.save_target_image(target_name, image_data, source=source)


class TNSObjectDB:
    @staticmethod
    def add_photometry_bulk(photometry_data):
        DataUploader.add_photometry_bulk(photometry_data)

    @staticmethod
    def sync_last_photometry_date(object_name: str):
        DataUploader.sync_last_photometry_date(object_name)

    @staticmethod
    def get_photometry(object_name: str) -> list[dict]:
        return DataFetcher.get_photometry(object_name)


tns_object_db = TNSObjectDB()

if __name__ == "__main__":
    # Test internal connection setup
    if check_db_connection():
        print("Database connection check passed successfully!")
    else:
        print("[ERROR] Database connection check failed.")