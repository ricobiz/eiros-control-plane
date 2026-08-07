from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from runtime.rental_agent.models import LeadInput, PropertyRecord

SCHEMA_VERSION = 1

SCHEMA_V1 = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS properties (
  property_id TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  project_name TEXT NOT NULL DEFAULT '',
  locality TEXT NOT NULL DEFAULT '',
  monthly_rent_vnd INTEGER,
  floors INTEGER,
  area_m2 REAL,
  lease_min_months INTEGER,
  deposit_months REAL,
  fit_score REAL NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS listing_sources (
  source_id TEXT PRIMARY KEY,
  property_id TEXT NOT NULL REFERENCES properties(property_id),
  source_kind TEXT NOT NULL,
  source_value TEXT NOT NULL,
  source_url TEXT NOT NULL DEFAULT '',
  raw_json TEXT NOT NULL DEFAULT '{}',
  captured_at INTEGER NOT NULL,
  UNIQUE(source_kind, source_value)
);
CREATE TABLE IF NOT EXISTS contacts (
  contact_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  value_normalized TEXT NOT NULL,
  display_value TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  UNIQUE(kind, value_normalized)
);
CREATE TABLE IF NOT EXISTS property_contacts (
  property_id TEXT NOT NULL REFERENCES properties(property_id),
  contact_id TEXT NOT NULL REFERENCES contacts(contact_id),
  provenance_source_id TEXT,
  PRIMARY KEY(property_id, contact_id)
);
CREATE TABLE IF NOT EXISTS audit_events (
  event_id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL,
  property_id TEXT,
  payload_json TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
"""


class RentalDatabase:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version == 0:
                connection.executescript(SCHEMA_V1)
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                connection.commit()
            elif version != SCHEMA_VERSION:
                raise RuntimeError(f"Unsupported rental DB schema version: {version}")

    def health(self) -> dict[str, Any]:
        with self._connect() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            properties = int(connection.execute("SELECT COUNT(*) FROM properties").fetchone()[0])
            sources = int(connection.execute("SELECT COUNT(*) FROM listing_sources").fetchone()[0])
        return {
            "ok": version == SCHEMA_VERSION,
            "schema_version": version,
            "properties": properties,
            "listing_sources": sources,
            "db_path": str(self.path),
        }

    def create_lead(self, lead: LeadInput) -> PropertyRecord:
        source_kind = lead.source_kind.strip().lower()
        source_value = lead.source_value.strip()
        if not source_kind:
            raise ValueError("source_kind is required")
        if not source_value:
            raise ValueError("source_value is required")

        now = int(time.time())
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT property_id FROM listing_sources WHERE source_kind = ? AND source_value = ?",
                (source_kind, source_value),
            ).fetchone()
            if existing is not None:
                record = self._get_property_from_connection(connection, str(existing["property_id"]))
                if record is None:
                    raise RuntimeError("Listing source references missing property")
                return record

            property_id = f"prop_{uuid.uuid4().hex}"
            source_id = f"src_{uuid.uuid4().hex}"
            connection.execute(
                "INSERT INTO properties(property_id, status, created_at, updated_at) VALUES (?, 'new', ?, ?)",
                (property_id, now, now),
            )
            connection.execute(
                """
                INSERT INTO listing_sources(
                    source_id, property_id, source_kind, source_value, source_url, raw_json, captured_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    property_id,
                    source_kind,
                    source_value,
                    lead.source_url.strip(),
                    json.dumps(lead.context, ensure_ascii=False, sort_keys=True),
                    now,
                ),
            )
            connection.execute(
                "INSERT INTO audit_events(event_id, event_type, property_id, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    f"evt_{uuid.uuid4().hex}",
                    "lead_ingested",
                    property_id,
                    json.dumps({"source_kind": source_kind, "source_value": source_value}, ensure_ascii=False),
                    now,
                ),
            )
            connection.commit()
            record = self._get_property_from_connection(connection, property_id)
            if record is None:
                raise RuntimeError("New property could not be read back")
            return record

    def get_property(self, property_id: str) -> PropertyRecord | None:
        with self._connect() as connection:
            return self._get_property_from_connection(connection, property_id)

    def list_properties(self, limit: int = 50) -> list[PropertyRecord]:
        bounded = max(1, min(int(limit), 500))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM properties ORDER BY fit_score DESC, updated_at DESC, property_id ASC LIMIT ?",
                (bounded,),
            ).fetchall()
        return [self._row_to_property(row) for row in rows]

    @staticmethod
    def _get_property_from_connection(
        connection: sqlite3.Connection, property_id: str
    ) -> PropertyRecord | None:
        row = connection.execute(
            "SELECT * FROM properties WHERE property_id = ?", (property_id,)
        ).fetchone()
        return None if row is None else RentalDatabase._row_to_property(row)

    @staticmethod
    def _row_to_property(row: sqlite3.Row) -> PropertyRecord:
        return PropertyRecord(
            property_id=str(row["property_id"]),
            status=str(row["status"]),
            title=str(row["title"]),
            project_name=str(row["project_name"]),
            locality=str(row["locality"]),
            monthly_rent_vnd=row["monthly_rent_vnd"],
            floors=row["floors"],
            area_m2=row["area_m2"],
            lease_min_months=row["lease_min_months"],
            deposit_months=row["deposit_months"],
            fit_score=float(row["fit_score"]),
            created_at=int(row["created_at"]),
            updated_at=int(row["updated_at"]),
        )
