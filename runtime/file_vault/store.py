from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import shutil
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Iterable, Iterator

from .models import VaultConfig, VaultFile, VaultShare

_FILE_ID_RE = re.compile(r'^[0-9a-f]{32}$')


class VaultStore:
    def __init__(self, config: VaultConfig):
        self.config = VaultConfig(
            root=Path(config.root),
            max_upload_bytes=int(config.max_upload_bytes),
            reserve_bytes=int(config.reserve_bytes),
            allowed_import_roots=tuple(Path(p) for p in config.allowed_import_roots),
        )
        self.root = self.config.root
        self.objects_root = self.root / 'objects'
        self.staging_root = self.root / 'staging'
        self.audit_root = self.root / 'audit'
        self.db_path = self.root / 'vault.sqlite3'
        for path in (self.root, self.objects_root, self.staging_root, self.audit_root):
            path.mkdir(parents=True, exist_ok=True)
            os.chmod(path, 0o700)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        return db

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA foreign_keys=ON')
            db.executescript(
                '''
                CREATE TABLE IF NOT EXISTS files (
                    file_id TEXT PRIMARY KEY,
                    original_name TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    object_relpath TEXT NOT NULL,
                    source TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS files_created_at_idx ON files(created_at DESC);
                CREATE INDEX IF NOT EXISTS files_display_name_idx ON files(display_name);
                CREATE TABLE IF NOT EXISTS shares (
                    share_id TEXT PRIMARY KEY,
                    file_id TEXT NOT NULL REFERENCES files(file_id) ON DELETE CASCADE,
                    token_hash TEXT UNIQUE NOT NULL,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    revoked_at INTEGER NULL,
                    access_count INTEGER NOT NULL DEFAULT 0,
                    last_access_at INTEGER NULL,
                    disposition TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS shares_file_id_idx ON shares(file_id);
                '''
            )

    @staticmethod
    def _safe_name(name: str, fallback: str = 'file.bin') -> str:
        value = Path(str(name or fallback)).name.strip().strip('\x00')
        if not value:
            value = fallback
        return value[:255]

    @staticmethod
    def _normalize_tags(tags: Iterable[str]) -> tuple[str, ...]:
        out: set[str] = set()
        for raw in tags:
            tag = str(raw).strip().lower()
            if not tag:
                continue
            if len(tag) > 64:
                raise ValueError('Tag exceeds 64 characters')
            out.add(tag)
            if len(out) > 32:
                raise ValueError('Maximum 32 tags')
        return tuple(sorted(out))

    @staticmethod
    def _validate_file_id(file_id: str) -> str:
        value = str(file_id or '').strip().lower()
        if not _FILE_ID_RE.fullmatch(value):
            raise ValueError('Invalid file_id')
        return value

    @staticmethod
    def _row_to_file(row: sqlite3.Row) -> VaultFile:
        raw_tags = json.loads(row['tags_json'] or '[]')
        return VaultFile(
            file_id=row['file_id'],
            original_name=row['original_name'],
            display_name=row['display_name'],
            media_type=row['media_type'],
            size_bytes=int(row['size_bytes']),
            sha256=row['sha256'],
            object_relpath=row['object_relpath'],
            source=row['source'],
            tags=tuple(str(x) for x in raw_tags),
            note=row['note'],
            created_at=int(row['created_at']),
            updated_at=int(row['updated_at']),
        )

    def health(self) -> dict[str, object]:
        with self._connect() as db:
            count, total = db.execute('SELECT COUNT(*), COALESCE(SUM(size_bytes),0) FROM files').fetchone()
        usage = shutil.disk_usage(self.root)
        return {
            'ok': True,
            'root': str(self.root),
            'db_path': str(self.db_path),
            'file_count': int(count),
            'stored_bytes': int(total),
            'free_bytes': int(usage.free),
            'max_upload_bytes': self.config.max_upload_bytes,
            'reserve_bytes': self.config.reserve_bytes,
        }

    def get(self, file_id: str) -> VaultFile:
        file_id = self._validate_file_id(file_id)
        with self._connect() as db:
            row = db.execute('SELECT * FROM files WHERE file_id=?', (file_id,)).fetchone()
        if row is None:
            raise FileNotFoundError(f'Unknown vault file: {file_id}')
        return self._row_to_file(row)

    def list(self, query: str = '', tag: str = '', limit: int = 50) -> list[VaultFile]:
        limit = max(1, min(int(limit), 200))
        query = str(query or '').strip().lower()
        tag = str(tag or '').strip().lower()
        clauses: list[str] = []
        params: list[object] = []
        if query:
            needle = f'%{query}%'
            clauses.append('(LOWER(display_name) LIKE ? OR LOWER(original_name) LIKE ? OR LOWER(note) LIKE ? OR LOWER(tags_json) LIKE ?)')
            params.extend([needle, needle, needle, needle])
        sql = 'SELECT * FROM files'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        sql += ' ORDER BY created_at DESC, file_id DESC LIMIT ?'
        params.append(limit)
        with self._connect() as db:
            rows = list(db.execute(sql, params))
        files = [self._row_to_file(row) for row in rows]
        if tag:
            files = [item for item in files if tag in item.tags]
        return files

    def _check_capacity(self, incoming_size: int) -> None:
        if incoming_size > self.config.max_upload_bytes:
            raise ValueError('File exceeds maximum upload size')
        free = int(shutil.disk_usage(self.root).free)
        if free - incoming_size < self.config.reserve_bytes:
            raise ValueError('Upload would violate free-space reserve')

    def _finalize_staging(
        self,
        staging: Path,
        *,
        filename: str,
        source: str,
        tags: Iterable[str],
        note: str,
        size_bytes: int,
        sha256_hex: str,
    ) -> VaultFile:
        file_id = uuid.uuid4().hex
        relpath = Path(file_id[:2]) / file_id
        final = self.objects_root / relpath
        final.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(final.parent, 0o700)
        os.replace(staging, final)
        original_name = self._safe_name(filename)
        display_name = original_name
        media_type = mimetypes.guess_type(original_name)[0] or 'application/octet-stream'
        normalized_tags = self._normalize_tags(tags)
        note = str(note or '')[:4000]
        now = int(time.time())
        try:
            with self._connect() as db:
                db.execute(
                    '''INSERT INTO files
                       (file_id,original_name,display_name,media_type,size_bytes,sha256,object_relpath,source,tags_json,note,created_at,updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (
                        file_id,
                        original_name,
                        display_name,
                        media_type,
                        size_bytes,
                        sha256_hex,
                        str(relpath),
                        str(source),
                        json.dumps(normalized_tags, ensure_ascii=False),
                        note,
                        now,
                        now,
                    ),
                )
        except Exception:
            final.unlink(missing_ok=True)
            raise
        return self.get(file_id)

    def store_stream(
        self,
        filename: str,
        chunks: Iterable[bytes],
        *,
        source: str = 'browser_upload',
        tags: Iterable[str] = (),
        note: str = '',
    ) -> VaultFile:
        staging = self.staging_root / f'{uuid.uuid4().hex}.part'
        digest = hashlib.sha256()
        size = 0
        try:
            with staging.open('xb') as fh:
                os.chmod(staging, 0o600)
                for chunk in chunks:
                    if not isinstance(chunk, (bytes, bytearray, memoryview)):
                        raise TypeError('Upload chunks must be bytes')
                    data = bytes(chunk)
                    if not data:
                        continue
                    size += len(data)
                    if size > self.config.max_upload_bytes:
                        raise ValueError('File exceeds maximum upload size')
                    fh.write(data)
                    digest.update(data)
                fh.flush()
                os.fsync(fh.fileno())
            self._check_capacity(size)
            return self._finalize_staging(
                staging,
                filename=filename,
                source=source,
                tags=tags,
                note=note,
                size_bytes=size,
                sha256_hex=digest.hexdigest(),
            )
        except Exception:
            staging.unlink(missing_ok=True)
            raise

    def store_bytes(
        self,
        filename: str,
        data: bytes,
        *,
        source: str = 'mcp_upload',
        tags: Iterable[str] = (),
        note: str = '',
    ) -> VaultFile:
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError('data must be bytes')
        payload = bytes(data)
        self._check_capacity(len(payload))
        return self.store_stream(filename, (payload,), source=source, tags=tags, note=note)

    def _is_allowed_import(self, path: Path) -> bool:
        resolved = path.resolve(strict=True)
        for root in self.config.allowed_import_roots:
            root_resolved = root.resolve(strict=True)
            if resolved == root_resolved or root_resolved in resolved.parents:
                return True
        return False

    def import_path(
        self,
        path: str | Path,
        *,
        display_name: str | None = None,
        tags: Iterable[str] = (),
        note: str = '',
    ) -> VaultFile:
        source_path = Path(path)
        resolved = source_path.resolve(strict=True)
        if not self._is_allowed_import(source_path):
            raise PermissionError('Import path is outside allowed roots')
        if not resolved.is_file():
            raise ValueError('Import path must be a regular file')
        size = resolved.stat().st_size
        self._check_capacity(size)

        def chunks() -> Iterator[bytes]:
            with resolved.open('rb') as fh:
                while True:
                    chunk = fh.read(1024 * 1024)
                    if not chunk:
                        break
                    yield chunk

        return self.store_stream(
            display_name or resolved.name,
            chunks(),
            source='vps_import',
            tags=tags,
            note=note,
        )

    def object_path(self, file_id: str) -> Path:
        item = self.get(file_id)
        candidate = (self.objects_root / item.object_relpath).resolve()
        root = self.objects_root.resolve()
        if root not in candidate.parents:
            raise FileNotFoundError('Stored object path is invalid')
        return candidate

    def read_bytes(self, file_id: str) -> bytes:
        return self.object_path(file_id).read_bytes()

    def verify(self, file_id: str) -> dict[str, object]:
        item = self.get(file_id)
        path = self.object_path(file_id)
        digest = hashlib.sha256()
        size = 0
        with path.open('rb') as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b''):
                size += len(chunk)
                digest.update(chunk)
        actual_hash = digest.hexdigest()
        return {
            'ok': size == item.size_bytes and actual_hash == item.sha256,
            'file_id': item.file_id,
            'expected_size_bytes': item.size_bytes,
            'actual_size_bytes': size,
            'expected_sha256': item.sha256,
            'actual_sha256': actual_hash,
        }

    def delete(self, file_id: str) -> dict[str, object]:
        item = self.get(file_id)
        path = self.object_path(file_id)
        object_missing = not path.exists()
        with self._connect() as db:
            db.execute('DELETE FROM files WHERE file_id=?', (item.file_id,))
        if not object_missing:
            path.unlink()
        return {'ok': True, 'deleted': True, 'file_id': item.file_id, 'object_missing': object_missing}
