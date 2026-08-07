from __future__ import annotations

import os
from pathlib import Path

DEFAULT_DATA_DIR = Path(os.environ.get("EIROS_RENTAL_DATA_DIR", "/var/lib/eiros-rental"))
DEFAULT_DB_PATH = DEFAULT_DATA_DIR / "rental.db"
DEFAULT_PORT = int(os.environ.get("EIROS_RENTAL_PORT", "8794"))
DEFAULT_HOST = os.environ.get("EIROS_RENTAL_HOST", "127.0.0.1")
