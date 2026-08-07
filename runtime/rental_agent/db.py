from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from runtime.rental_agent.dedup import property_signature
from runtime.rental_agent.models import LeadInput, PropertyRecord, UpsertResult
from runtime.rental_agent.normalize import NormalizedListing
from runtime.rental_agent.ranking import FitResult

SCHEMA_VERSION = 2

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

MIGRATION_V2 = """
ALTER TABLE properties ADD COLUMN whole_building INTEGER;
ALTER TABLE properties ADD COLUMN score_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE properties ADD COLUMN signature TEXT NOT NULL DEFAULT '';
ALTER TABLE properties ADD COLUMN last_seen_at INTEGER NOT NULL DEFAULT 0;
ALTER TABLE listing_sources ADD COLUMN title TEXT NOT NULL DEFAULT '';
ALTER TABLE listing_sources ADD COLUMN body_text TEXT NOT NULL DEFAULT '';
ALTER TABLE listing_sources ADD COLUMN fingerprint TEXT NOT NULL DEFAULT '';
ALTER TABLE listing_sources ADD COLUMN last_seen_at INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_properties_signature ON properties(signature);
CREATE INDEX IF NOT EXISTS idx_sources_fingerprint ON listing_sources(fingerprint);
CREATE TABLE IF NOT EXISTS observations (
  observation_id TEXT PRIMARY KEY,
  property_id TEXT NOT NULL REFERENCES properties(property_id),
  source_id TEXT REFERENCES listing_sources(source_id),
  kind TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  observed_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS search_runs (
  run_id TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  query_json TEXT NOT NULL,
  result_count INTEGER NOT NULL DEFAULT 0,
  error_count INTEGER NOT NULL DEFAULT 0,
  started_at INTEGER NOT NULL,
  finished_at INTEGER
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
                connection.executescript(MIGRATION_V2)
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                connection.commit()
            elif version == 1:
                connection.executescript(MIGRATION_V2)
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                connection.commit()
            elif version != SCHEMA_VERSION:
                raise RuntimeError(f"Unsupported rental DB schema version: {version}")

    def health(self) -> dict[str, Any]:
        with self._connect() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            properties = int(connection.execute("SELECT COUNT(*) FROM properties").fetchone()[0])
            sources = int(connection.execute("SELECT COUNT(*) FROM listing_sources").fetchone()[0])
            runs = int(connection.execute("SELECT COUNT(*) FROM search_runs").fetchone()[0]) if version >= 2 else 0
        return {
            "ok": version == SCHEMA_VERSION,
            "schema_version": version,
            "properties": properties,
            "listing_sources": sources,
            "search_runs": runs,
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
                "INSERT INTO properties(property_id, status, created_at, updated_at, last_seen_at) VALUES (?, 'new', ?, ?, ?)",
                (property_id, now, now, now),
            )
            connection.execute(
                """INSERT INTO listing_sources(
                    source_id, property_id, source_kind, source_value, source_url, raw_json, captured_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    source_id,
                    property_id,
                    source_kind,
                    source_value,
                    lead.source_url.strip(),
                    json.dumps(lead.context, ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                ),
            )
            self._audit(connection, "lead_ingested", property_id, {"source_kind": source_kind, "source_value": source_value}, now)
            connection.commit()
            record = self._get_property_from_connection(connection, property_id)
            if record is None:
                raise RuntimeError("New property could not be read back")
            return record

    def upsert_normalized_source(self, lead: LeadInput, item: NormalizedListing, fit: FitResult) -> UpsertResult:
        source_kind = lead.source_kind.strip().lower()
        source_value = lead.source_value.strip()
        if not source_kind or not source_value:
            raise ValueError("source_kind and source_value are required")
        now = int(time.time())
        signature = property_signature(item)
        with self._connect() as connection:
            existing_source = connection.execute(
                "SELECT source_id, property_id FROM listing_sources WHERE source_kind=? AND source_value=?",
                (source_kind, source_value),
            ).fetchone()
            property_id: str | None = None
            source_id: str | None = None
            merged = False
            if existing_source:
                property_id = str(existing_source["property_id"])
                source_id = str(existing_source["source_id"])
                merged = True
            if property_id is None and signature:
                row = connection.execute(
                    "SELECT property_id FROM properties WHERE signature=? ORDER BY updated_at DESC LIMIT 1",
                    (signature,),
                ).fetchone()
                if row:
                    property_id = str(row["property_id"])
                    merged = True
            if property_id is None and item.text_fingerprint:
                row = connection.execute(
                    "SELECT property_id FROM listing_sources WHERE fingerprint=? LIMIT 1",
                    (item.text_fingerprint,),
                ).fetchone()
                if row:
                    property_id = str(row["property_id"])
                    merged = True
            if property_id is None:
                property_id = f"prop_{uuid.uuid4().hex}"
                connection.execute(
                    "INSERT INTO properties(property_id,status,created_at,updated_at,last_seen_at) VALUES (?, 'new', ?, ?, ?)",
                    (property_id, now, now, now),
                )

            status = "rejected" if fit.hard_reject else ("qualified" if fit.total >= 65 else "candidate")
            current = connection.execute("SELECT * FROM properties WHERE property_id=?", (property_id,)).fetchone()
            assert current is not None
            def choose(new: Any, old: Any) -> Any:
                return old if new in (None, "") else new
            connection.execute(
                """UPDATE properties SET status=?, title=?, project_name=?, locality=?, monthly_rent_vnd=?,
                   floors=?, area_m2=?, lease_min_months=?, deposit_months=?, whole_building=?, fit_score=?,
                   score_json=?, signature=?, updated_at=?, last_seen_at=? WHERE property_id=?""",
                (
                    status,
                    choose(item.title, current["title"]),
                    choose(item.project_name, current["project_name"]),
                    choose(item.locality, current["locality"]),
                    choose(item.monthly_rent_vnd, current["monthly_rent_vnd"]),
                    choose(item.floors, current["floors"]),
                    choose(item.area_m2, current["area_m2"]),
                    choose(item.lease_min_months, current["lease_min_months"]),
                    choose(item.deposit_months, current["deposit_months"]),
                    (None if item.whole_building is None and current["whole_building"] is None else int(item.whole_building) if item.whole_building is not None else current["whole_building"]),
                    fit.total,
                    json.dumps(fit.dimensions, sort_keys=True),
                    signature or str(current["signature"] or ""),
                    now,
                    now,
                    property_id,
                ),
            )

            if source_id is None:
                source_id = f"src_{uuid.uuid4().hex}"
                connection.execute(
                    """INSERT INTO listing_sources(
                       source_id,property_id,source_kind,source_value,source_url,raw_json,captured_at,title,body_text,fingerprint,last_seen_at
                       ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        source_id, property_id, source_kind, source_value, lead.source_url.strip(),
                        json.dumps(lead.context, ensure_ascii=False, sort_keys=True), now, item.title,
                        item.raw_text, item.text_fingerprint, now,
                    ),
                )
            else:
                connection.execute(
                    """UPDATE listing_sources SET source_url=?,raw_json=?,title=?,body_text=?,fingerprint=?,last_seen_at=?
                       WHERE source_id=?""",
                    (
                        lead.source_url.strip(), json.dumps(lead.context, ensure_ascii=False, sort_keys=True),
                        item.title, item.raw_text, item.text_fingerprint, now, source_id,
                    ),
                )

            for phone in item.phones:
                row = connection.execute("SELECT contact_id FROM contacts WHERE kind='phone' AND value_normalized=?", (phone,)).fetchone()
                contact_id = str(row["contact_id"]) if row else f"contact_{uuid.uuid4().hex}"
                if row is None:
                    connection.execute(
                        "INSERT INTO contacts(contact_id,kind,value_normalized,display_value,created_at) VALUES (?,'phone',?,?,?)",
                        (contact_id, phone, phone, now),
                    )
                connection.execute(
                    "INSERT OR IGNORE INTO property_contacts(property_id,contact_id,provenance_source_id) VALUES (?,?,?)",
                    (property_id, contact_id, source_id),
                )

            connection.execute(
                "INSERT INTO observations(observation_id,property_id,source_id,kind,payload_json,observed_at) VALUES (?,?,?,?,?,?)",
                (
                    f"obs_{uuid.uuid4().hex}", property_id, source_id, "normalized_listing",
                    json.dumps({
                        "price_vnd": item.monthly_rent_vnd, "floors": item.floors, "area_m2": item.area_m2,
                        "lease_min_months": item.lease_min_months, "deposit_months": item.deposit_months,
                        "whole_building": item.whole_building, "fit": fit.dimensions, "reasons": fit.reasons,
                    }, ensure_ascii=False, sort_keys=True), now,
                ),
            )
            self._audit(connection, "listing_upserted", property_id, {"source_id": source_id, "merged": merged, "fit_score": fit.total}, now)
            connection.commit()
            record = self._get_property_from_connection(connection, property_id)
            if record is None:
                raise RuntimeError("Property could not be read after upsert")
            return UpsertResult(property=record, source_id=source_id, merged=merged)

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

    def list_sources(self, property_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM listing_sources WHERE property_id=? ORDER BY last_seen_at DESC, captured_at DESC",
                (property_id,),
            ).fetchall()
        return [dict(row) | {"raw": json.loads(str(row["raw_json"] or "{}"))} for row in rows]

    def list_contacts(self, property_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT c.contact_id,c.kind,c.value_normalized,c.display_value,pc.provenance_source_id
                   FROM property_contacts pc JOIN contacts c ON c.contact_id=pc.contact_id
                   WHERE pc.property_id=? ORDER BY c.created_at ASC""",
                (property_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def begin_search_run(self, query: dict[str, Any]) -> str:
        run_id = f"run_{uuid.uuid4().hex}"
        now = int(time.time())
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO search_runs(run_id,status,query_json,started_at) VALUES (?,?,?,?)",
                (run_id, "running", json.dumps(query, ensure_ascii=False, sort_keys=True), now),
            )
            connection.commit()
        return run_id

    def finish_search_run(self, run_id: str, *, status: str, result_count: int, error_count: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE search_runs SET status=?,result_count=?,error_count=?,finished_at=? WHERE run_id=?",
                (status, int(result_count), int(error_count), int(time.time()), run_id),
            )
            connection.commit()

    def list_search_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 100))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM search_runs ORDER BY started_at DESC, run_id DESC LIMIT ?", (bounded,)
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["query"] = json.loads(str(row["query_json"] or "{}"))
            result.append(item)
        return result

    @staticmethod
    def _audit(connection: sqlite3.Connection, event_type: str, property_id: str | None, payload: dict[str, Any], now: int) -> None:
        connection.execute(
            "INSERT INTO audit_events(event_id,event_type,property_id,payload_json,created_at) VALUES (?,?,?,?,?)",
            (f"evt_{uuid.uuid4().hex}", event_type, property_id, json.dumps(payload, ensure_ascii=False, sort_keys=True), now),
        )

    @staticmethod
    def _get_property_from_connection(connection: sqlite3.Connection, property_id: str) -> PropertyRecord | None:
        row = connection.execute("SELECT * FROM properties WHERE property_id=?", (property_id,)).fetchone()
        return None if row is None else RentalDatabase._row_to_property(row)

    @staticmethod
    def _row_to_property(row: sqlite3.Row) -> PropertyRecord:
        whole = row["whole_building"]
        return PropertyRecord(
            property_id=str(row["property_id"]), status=str(row["status"]), title=str(row["title"]),
            project_name=str(row["project_name"]), locality=str(row["locality"]),
            monthly_rent_vnd=row["monthly_rent_vnd"], floors=row["floors"], area_m2=row["area_m2"],
            lease_min_months=row["lease_min_months"], deposit_months=row["deposit_months"],
            whole_building=None if whole is None else bool(whole), fit_score=float(row["fit_score"]),
            fit_dimensions=json.loads(str(row["score_json"] or "{}")), signature=str(row["signature"] or ""),
            created_at=int(row["created_at"]), updated_at=int(row["updated_at"]),
        )
