from __future__ import annotations

import os
from pathlib import Path

DEFAULT_DATA_DIR = Path(os.environ.get("EIROS_RENTAL_DATA_DIR", "/var/lib/eiros-rental"))
DEFAULT_DB_PATH = DEFAULT_DATA_DIR / "rental.db"
DEFAULT_PORT = int(os.environ.get("EIROS_RENTAL_PORT", "8794"))
DEFAULT_HOST = os.environ.get("EIROS_RENTAL_HOST", "127.0.0.1")

DEFAULT_SEARCH_PROFILE = {
    "country": "Vietnam",
    "location": "Phu Quoc",
    "zones": ["Sunset Town", "Primavera", "The Center", "nearby New An Thoi"],
    "property_type": "whole shophouse/building only",
    "floors": {"min": 3, "max": 6, "preferred": [5, 6]},
    "budget_vnd_month": {
        "target_min": 18_000_000,
        "target_max": 25_000_000,
        "stretch_max": 30_000_000,
    },
    "unfinished_shell_ok": True,
    "hotel_room_layout_ok": True,
}
