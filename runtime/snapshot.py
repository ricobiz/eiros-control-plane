from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from runtime.config import DATA_ROOT, load_config
from runtime.version import __version__

SNAPSHOT_SCHEMA = 1
DURABLE_FILES = (
    "config/instance.json",
    "state.json",
    ".eiros-state.json",
    "JOURNAL.md",
    "runtime/queue.json",
    "runtime/events.json",
    "runtime/brain-inbox.json",
    "runtime/installation.json",
    "runtime/server-status.json",
)
DURABLE_DIRS = ("tasks", "memory")
META_DIR = ".eiros-snapshot"
MANIFEST_NAME = f"{META_DIR}/manifest.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_durable_files(root: Path) -> Iterable[Path]:
    seen: set[Path] = set()
    for relative in DURABLE_FILES:
        candidate = root / relative
        if candidate.is_file() and candidate not in seen:
            seen.add(candidate)
            yield candidate
    for relative in DURABLE_DIRS:
        directory = root / relative
        if not directory.is_dir():
            continue
        for candidate in sorted(directory.rglob("*")):
            if candidate.is_file() and not candidate.is_symlink() and candidate not in seen:
                seen.add(candidate)
                yield candidate


def create_snapshot(output: Path, root: Path = DATA_ROOT) -> dict[str, Any]:
    root = root.resolve()
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    config = load_config() if root == DATA_ROOT else _read_instance_config(root)
    files: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="eiros-snapshot-") as temp_name:
        staging = Path(temp_name)
        for source in iter_durable_files(root):
            relative = source.relative_to(root)
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            files.append({
                "path": relative.as_posix(),
                "size": target.stat().st_size,
                "sha256": sha256_file(target),
                "mode": target.stat().st_mode & 0o777,
            })

        manifest = {
            "snapshot_schema": SNAPSHOT_SCHEMA,
            "created_at": int(time.time()),
            "eiros_version": __version__,
            "instance_id": config.get("instance_id"),
            "channel": config.get("channel", "default"),
            "source_root": str(root),
            "files": files,
        }
        manifest_path = staging / MANIFEST_NAME
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.unlink(missing_ok=True)
        with tarfile.open(temporary, "w:gz", format=tarfile.PAX_FORMAT) as archive:
            for entry in sorted(staging.rglob("*")):
                if entry.is_file():
                    archive.add(entry, arcname=entry.relative_to(staging).as_posix(), recursive=False)
        os.replace(temporary, output)

    return {
        "ok": True,
        "path": str(output),
        "size": output.stat().st_size,
        "sha256": sha256_file(output),
        "manifest": manifest,
    }


def inspect_snapshot(snapshot: Path) -> dict[str, Any]:
    snapshot = snapshot.expanduser().resolve()
    with tarfile.open(snapshot, "r:gz") as archive:
        members = archive.getmembers()
        _validate_members(members)
        manifest_member = archive.getmember(MANIFEST_NAME)
        manifest_handle = archive.extractfile(manifest_member)
        if manifest_handle is None:
            raise RuntimeError("Snapshot manifest is unreadable")
        manifest = json.loads(manifest_handle.read().decode("utf-8"))
    if int(manifest.get("snapshot_schema", 0)) != SNAPSHOT_SCHEMA:
        raise RuntimeError("Unsupported snapshot schema")
    return {
        "ok": True,
        "path": str(snapshot),
        "size": snapshot.stat().st_size,
        "sha256": sha256_file(snapshot),
        "manifest": manifest,
    }


def restore_snapshot(snapshot: Path, target_root: Path, force: bool = False) -> dict[str, Any]:
    snapshot = snapshot.expanduser().resolve()
    target_root = target_root.expanduser().resolve()
    if target_root.exists() and any(target_root.iterdir()) and not force:
        raise RuntimeError("Target data directory is not empty; use force only after taking a backup")
    target_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="eiros-restore-") as temp_name:
        staging = Path(temp_name)
        with tarfile.open(snapshot, "r:gz") as archive:
            members = archive.getmembers()
            _validate_members(members)
            archive.extractall(staging, members=members, filter="data")

        manifest = json.loads((staging / MANIFEST_NAME).read_text(encoding="utf-8"))
        if int(manifest.get("snapshot_schema", 0)) != SNAPSHOT_SCHEMA:
            raise RuntimeError("Unsupported snapshot schema")

        expected = {entry["path"]: entry for entry in manifest.get("files", [])}
        for relative, metadata in expected.items():
            source = staging / relative
            if not source.is_file():
                raise RuntimeError(f"Snapshot file missing: {relative}")
            if source.stat().st_size != int(metadata["size"]):
                raise RuntimeError(f"Snapshot size mismatch: {relative}")
            if sha256_file(source) != metadata["sha256"]:
                raise RuntimeError(f"Snapshot checksum mismatch: {relative}")

        if force:
            for relative in list(DURABLE_FILES) + list(DURABLE_DIRS):
                current = target_root / relative
                if current.is_dir():
                    shutil.rmtree(current)
                elif current.exists():
                    current.unlink()

        for relative, metadata in expected.items():
            source = staging / relative
            destination = target_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            os.chmod(destination, int(metadata.get("mode", 0o600)))

    return {
        "ok": True,
        "snapshot": str(snapshot),
        "target_root": str(target_root),
        "instance_id": manifest.get("instance_id"),
        "files_restored": len(manifest.get("files", [])),
    }


def _read_instance_config(root: Path) -> dict[str, Any]:
    path = root / "config" / "instance.json"
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _validate_members(members: list[tarfile.TarInfo]) -> None:
    names = {member.name for member in members}
    if MANIFEST_NAME not in names:
        raise RuntimeError("Snapshot manifest is missing")
    for member in members:
        pure = PurePosixPath(member.name)
        if pure.is_absolute() or ".." in pure.parts:
            raise RuntimeError(f"Unsafe archive path: {member.name}")
        if member.issym() or member.islnk() or member.isdev():
            raise RuntimeError(f"Unsupported archive member: {member.name}")
