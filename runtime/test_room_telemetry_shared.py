"""Regression tests for the shared widget-telemetry store.

room_telemetry.json is written by two services running as two different uids
(eiros-claude.service as `eiros`, the operator surface as `root`). Before this
module existed the file was published with the bare mkstemp default and sat on
disk as 0600, so whichever side wrote last owned it outright. These tests pin
the contract that makes it writable from both sides.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from runtime import room_telemetry
from runtime.config import SHARED_GROUP


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """RUNTIME_DIR is resolved at import time, so redirect the module's paths.

    Without this every test in the file shares one store and they read each
    other's rows.
    """
    monkeypatch.setattr(room_telemetry, "TELEMETRY_FILE", tmp_path / "room_telemetry.json")
    monkeypatch.setattr(room_telemetry, "LOCK_FILE", tmp_path / "room_telemetry.lock")
    return tmp_path


def test_record_creates_group_writable_state_and_lock():
    room_telemetry.record(widget_id="w1", widget_kind="claude-pulse", status="html-parsed:ok")
    for path in (room_telemetry.TELEMETRY_FILE, room_telemetry.LOCK_FILE):
        assert path.exists(), f"{path.name} was not created"
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode & 0o060 == 0o060, f"{path.name} is {oct(mode)}, group cannot read+write it"


def test_existing_owner_only_file_is_repaired_not_preserved():
    """A file already on disk as 0600 must be widened, not left as it is.

    This is the exact production state room_telemetry.json was found in, and a
    publish path that only ORs group-read leaves the second writer locked out.
    """
    room_telemetry.record(widget_id="w1", status="html-parsed:ok")
    os.chmod(room_telemetry.TELEMETRY_FILE, 0o600)
    os.chmod(room_telemetry.LOCK_FILE, 0o600)
    room_telemetry.record(widget_id="w2", status="first-tool-call:ok")
    for path in (room_telemetry.TELEMETRY_FILE, room_telemetry.LOCK_FILE):
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode & 0o060 == 0o060, f"{path.name} stayed {oct(mode)} after a second write"


def test_record_round_trips_and_keeps_other_widgets():
    room_telemetry.record(widget_id="a", status="html-parsed:ok")
    room_telemetry.record(widget_id="b", status="wake-sdk:fail", error="boom")
    widgets = room_telemetry.read()["widgets"]
    assert set(widgets) == {"a", "b"}
    assert widgets["b"]["error"] == "boom"
    assert widgets["b"]["status"] == "wake-sdk:fail"


def test_blank_widget_id_is_rejected():
    with pytest.raises(ValueError):
        room_telemetry.record(widget_id="   ")


def test_oversized_snapshot_is_truncated_not_dropped():
    room_telemetry.record(widget_id="big", status="x", snapshot={"blob": "y" * 20000})
    stored = room_telemetry.read()["widgets"]["big"]["snapshot"]
    assert stored.get("truncated") is True
    assert len(json.dumps(stored)) < 20000


def test_unreadable_file_reports_error_instead_of_masking():
    room_telemetry.TELEMETRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    room_telemetry.TELEMETRY_FILE.write_text("{not json", encoding="utf-8")
    store = room_telemetry.read()
    assert store["widgets"] == {}
    assert store.get("read_error")


@pytest.mark.skipif(os.geteuid() != 0, reason="cross-uid write needs root to drop privileges")
def test_second_uid_can_write_after_the_first():
    """The whole point: root writes, then eiros writes, and neither is locked out.

    Not using tmp_path: pytest's own tmp tree is 0700 root, so the unprivileged
    side cannot even traverse into it and the test would fail for a reason that
    has nothing to do with the contract under test.
    """
    import grp
    import shutil
    import tempfile

    try:
        grp.getgrnam(SHARED_GROUP)
    except KeyError:
        pytest.skip(f"group {SHARED_GROUP} does not exist on this host")

    base = Path(tempfile.mkdtemp(prefix="eiros-xuid-", dir="/tmp"))
    try:
        os.chmod(base, 0o755)
        data_dir = base / "data"
        (data_dir / "runtime").mkdir(parents=True)
        subprocess.run(["chown", "-R", f"{SHARED_GROUP}:{SHARED_GROUP}", str(data_dir)], check=True)
        os.chmod(data_dir, 0o755)
        os.chmod(data_dir / "runtime", 0o2775)

        code_root = str(Path(__file__).resolve().parents[1])
        script = (
            "import sys;"
            "from runtime import room_telemetry as rt;"
            "rt.record(widget_id=sys.argv[1], status='ok');"
            "print(sorted((rt.read().get('widgets') or {}).keys()))"
        )
        env = dict(os.environ, EIROS_DATA_DIR=str(data_dir), PYTHONPATH=code_root)

        as_root = subprocess.run([sys.executable, "-c", script, "by-root"],
                                 env=env, cwd=code_root, capture_output=True, text=True)
        assert as_root.returncode == 0, as_root.stderr

        as_eiros = subprocess.run(
            ["sudo", "-u", SHARED_GROUP, "env", f"EIROS_DATA_DIR={data_dir}",
             f"PYTHONPATH={code_root}", sys.executable, "-c", script, "by-eiros"],
            cwd=code_root, capture_output=True, text=True,
        )
        assert as_eiros.returncode == 0, as_eiros.stderr
        assert "by-root" in as_eiros.stdout and "by-eiros" in as_eiros.stdout

        # And back again: the eiros write must not have locked root out either.
        as_root_again = subprocess.run([sys.executable, "-c", script, "by-root-2"],
                                       env=env, cwd=code_root, capture_output=True, text=True)
        assert as_root_again.returncode == 0, as_root_again.stderr
        assert "by-eiros" in as_root_again.stdout

        state = json.loads((data_dir / "runtime" / "room_telemetry.json").read_text())
        assert set(state["widgets"]) == {"by-root", "by-eiros", "by-root-2"}
    finally:
        shutil.rmtree(base, ignore_errors=True)
