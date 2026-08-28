from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class VaultConfig:
    root: Path
    max_upload_bytes: int = 2 * 1024**3
    reserve_bytes: int = 2 * 1024**3
    allowed_import_roots: tuple[Path, ...] = (
        Path('/var/lib/eiros'),
        Path('/opt/eiros-control-plane'),
    )


@dataclass(frozen=True)
class VaultFile:
    file_id: str
    original_name: str
    display_name: str
    media_type: str
    size_bytes: int
    sha256: str
    object_relpath: str
    source: str
    tags: tuple[str, ...]
    note: str
    created_at: int
    updated_at: int

    def as_dict(self) -> dict[str, object]:
        return {
            'file_id': self.file_id,
            'original_name': self.original_name,
            'display_name': self.display_name,
            'media_type': self.media_type,
            'size_bytes': self.size_bytes,
            'sha256': self.sha256,
            'source': self.source,
            'tags': list(self.tags),
            'note': self.note,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }


@dataclass(frozen=True)
class VaultShare:
    share_id: str
    file_id: str
    token_hash: str
    created_at: int
    expires_at: int
    revoked_at: int | None
    access_count: int
    last_access_at: int | None
    disposition: str

    def as_dict(self) -> dict[str, object]:
        return {
            'share_id': self.share_id,
            'file_id': self.file_id,
            'created_at': self.created_at,
            'expires_at': self.expires_at,
            'revoked_at': self.revoked_at,
            'access_count': self.access_count,
            'last_access_at': self.last_access_at,
            'disposition': self.disposition,
        }
