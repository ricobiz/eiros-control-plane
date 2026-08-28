from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path

import pytest

from runtime.file_vault import VaultConfig, VaultStore


def make_store(tmp_path: Path, *, max_upload_bytes: int = 1024 * 1024, reserve_bytes: int = 1024) -> VaultStore:
    allowed = tmp_path / "allowed"
    allowed.mkdir(exist_ok=True)
    return VaultStore(
        VaultConfig(
            root=tmp_path / "vault",
            max_upload_bytes=max_upload_bytes,
            reserve_bytes=reserve_bytes,
            allowed_import_roots=(allowed,),
        )
    )


def test_store_initializes_private_layout_and_sqlite(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    root = store.config.root
    assert (root / "objects").is_dir()
    assert (root / "staging").is_dir()
    assert (root / "audit").is_dir()
    assert (root.stat().st_mode & 0o777) == 0o700

    with sqlite3.connect(root / "vault.sqlite3") as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        db.execute("PRAGMA foreign_keys=ON")
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"files", "shares"}.issubset(tables)


def test_store_bytes_is_exact_and_metadata_searchable(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    data = b"\x00\x01abc\xff"
    saved = store.store_bytes("../Face Test.PNG", data, tags=[" Avatar ", "LAM", "avatar"], note="reference face")

    assert len(saved.file_id) == 32
    assert saved.original_name == "Face Test.PNG"
    assert saved.display_name == "Face Test.PNG"
    assert saved.size_bytes == len(data)
    assert saved.sha256 == hashlib.sha256(data).hexdigest()
    assert saved.tags == ("avatar", "lam")
    assert store.read_bytes(saved.file_id) == data
    assert "Face Test.PNG" not in str(store.object_path(saved.file_id))
    assert store.list(query="reference")[0].file_id == saved.file_id
    assert store.list(tag="LAM")[0].file_id == saved.file_id


def test_upload_limit_and_failed_stream_leave_no_partial_state(tmp_path: Path) -> None:
    store = make_store(tmp_path, max_upload_bytes=5)
    with pytest.raises(ValueError, match="maximum"):
        store.store_bytes("too.bin", b"123456")
    assert list((store.config.root / "staging").iterdir()) == []
    assert list((store.config.root / "objects").rglob("*")) == []
    assert store.list() == []

    def broken():
        yield b"12"
        yield b"34"
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        store.store_stream("broken.bin", broken())
    assert list((store.config.root / "staging").iterdir()) == []
    assert store.list() == []


def test_disk_reserve_is_enforced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = make_store(tmp_path, reserve_bytes=100)

    class Usage:
        total = 1000
        used = 850
        free = 150

    monkeypatch.setattr("runtime.file_vault.store.shutil.disk_usage", lambda _path: Usage())
    with pytest.raises(ValueError, match="free-space reserve"):
        store.store_bytes("x.bin", b"x" * 60)


def test_import_allowed_file_rejects_outside_and_symlink_escape(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    allowed = store.config.allowed_import_roots[0]
    source = allowed / "sample.dat"
    source.write_bytes(b"hello import")

    imported = store.import_path(source, display_name="imported.dat", tags=["asset"])
    assert imported.display_name == "imported.dat"
    assert store.read_bytes(imported.file_id) == b"hello import"
    assert source.read_bytes() == b"hello import"

    outside = tmp_path / "outside.dat"
    outside.write_bytes(b"secret")
    with pytest.raises(PermissionError):
        store.import_path(outside)

    link = allowed / "escape.dat"
    link.symlink_to(outside)
    with pytest.raises(PermissionError):
        store.import_path(link)


def test_verify_and_delete_remove_object_and_metadata(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    saved = store.store_bytes("verify.bin", b"abcdef")
    result = store.verify(saved.file_id)
    assert result["ok"] is True
    assert result["actual_sha256"] == saved.sha256
    assert result["actual_size_bytes"] == 6

    path = store.object_path(saved.file_id)
    deleted = store.delete(saved.file_id)
    assert deleted["deleted"] is True
    assert not path.exists()
    with pytest.raises(FileNotFoundError):
        store.get(saved.file_id)
