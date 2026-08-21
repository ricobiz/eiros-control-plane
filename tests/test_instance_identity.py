"""The host identity must never be replaced by a read failure.

runtime/collab.py derives the hub agent id from config instance_id and
runtime/reconnect.py keys the reconnect envelope on it, so a regenerated
instance_id orphans every existing registration and leaves the old one behind
as a stale participant.
"""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

READ_ID = textwrap.dedent(
    """
    import json, sys
    from runtime.config import ensure_instance_config
    try:
        print(json.dumps({"ok": True, "instance_id": ensure_instance_config()["instance_id"]}))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
    """
)


def _run(data_root: Path) -> dict:
    env = dict(os.environ)
    env["EIROS_DATA_DIR"] = str(data_root)
    env["PYTHONPATH"] = str(ROOT)
    env.pop("EIROS_WIDGET_DOMAIN", None)
    proc = subprocess.run(
        [sys.executable, "-c", READ_ID], cwd=ROOT, env=env,
        text=True, capture_output=True, check=True,
    )
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_first_run_mints_an_identity(tmp_path):
    result = _run(tmp_path)
    assert result["ok"]
    assert result["instance_id"]


def test_identity_is_stable_across_calls(tmp_path):
    first = _run(tmp_path)["instance_id"]
    assert _run(tmp_path)["instance_id"] == first


def test_unreadable_config_does_not_mint_a_new_identity(tmp_path):
    original = _run(tmp_path)["instance_id"]
    config = tmp_path / "config" / "instance.json"
    config.chmod(0o000)
    try:
        if os.geteuid() == 0:
            pytest.skip("root can read a 0000 file, so the failure cannot be provoked here")
        result = _run(tmp_path)
        assert result["ok"] is False
        assert "instance_id" in result["error"]
    finally:
        config.chmod(0o600)
    assert _run(tmp_path)["instance_id"] == original


def test_corrupt_config_does_not_mint_a_new_identity(tmp_path):
    original = _run(tmp_path)["instance_id"]
    config = tmp_path / "config" / "instance.json"
    config.write_text("{ this is not json", encoding="utf-8")
    result = _run(tmp_path)
    assert result["ok"] is False
    assert "instance_id" in result["error"]
    config.write_text(json.dumps({"instance_id": original}), encoding="utf-8")
    assert _run(tmp_path)["instance_id"] == original


def test_shared_state_is_published_group_readable(tmp_path):
    _run(tmp_path)
    config = tmp_path / "config" / "instance.json"
    assert config.stat().st_mode & 0o040, "shared state must stay group-readable"
