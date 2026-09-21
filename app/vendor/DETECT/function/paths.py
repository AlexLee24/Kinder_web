"""Where DETECT keeps its files.

Stand-alone: ``<repo>/data``. Embedded in another program (the Kinder web app
vendors ``function/``): set ``DETECT_DATA_DIR`` to a writable directory; the
dust maps are fetched there on first use.
"""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = Path(os.getenv("DETECT_DATA_DIR") or (PROJECT_ROOT / "data")).expanduser()
