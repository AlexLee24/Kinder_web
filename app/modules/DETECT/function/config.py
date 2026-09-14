import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

ENV_PATH = PROJECT_ROOT / ".env"

if ENV_PATH.exists():
    load_dotenv(str(ENV_PATH))
else:
    print(f"Warning: .env file not found at {ENV_PATH}")

def get_env(key: str, default: str = "") -> str:
    """Helper function to fetch environment variables, ensuring a str is always returned."""
    val = os.getenv(key)
    if val is None:
        return default
    return val