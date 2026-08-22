"""The diagnostic channel must not lie and must not lose its own evidence.

Two defects motivated these tests, both found by executing the code rather than
reading it, and both still live on main after being reported fixed:

  1. every legacy alias rendered through the canonical URI, so a cached legacy
     card re-hydrating closed a fresh canonical mount the host had not fetched.
     The tool-call -> fetch correlation is the one thing this diagnostic exists
     to establish, and it was stealable.
  2. a store that failed to parse was silently reset to a single row, with the
     parse error written back in as state. One corrupt byte erased the ledger.
"""
from __future__ import annotations

import json
import os

import pytest

import runtime.claude_server as claude_server
from runtime import room_telemetry


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(room_telemetry, "TELEMETRY_FILE", tmp_path / "room_telemetry.json")
    monkeypatch.setattr(room_telemetry, "LOCK_FILE", tmp_path / "room_telemetry.lock")
    return tmp_path


def _status(mount_id):
    return room_telemetry.read()["widgets"][mount_id]["status"]


def _orphans():
    return [
        row["widget_id"] for row in room_telemetry.recent(50)
        if "no-recorded-tool-call" in row["status"]
    ]


@pytest.mark.parametrize("legacy", ["v5", "v4", "v3"])
def test_legacy_fetch_does_not_satisfy_a_pending_canonical_mount(legacy):
    mount_id = claude_server.open_claude_pulse()["mount_id"]
    assert _status(mount_id) == "mount-requested:wait"

    getattr(claude_server, f"claude_pulse_resource_legacy_{legacy}")()

    assert _status(mount_id) == "mount-requested:wait", (
        f"a legacy {legacy} fetch closed a canonical mount the host never fetched"
    )
    assert _orphans(), "the legacy fetch left no trace at all"


def test_canonical_fetch_still_satisfies_its_own_mount():
    mount_id = claude_server.open_claude_pulse()["mount_id"]
    claude_server.claude_pulse_resource()
    assert _status(mount_id) == "resource-served:ok"
    assert not _orphans(), "the canonical fetch was misrecorded as an orphan"


def test_rendered_widget_declares_which_uri_served_it():
    html = claude_server.claude_pulse_resource_legacy_v5()
    start = html.index("window.__EIROS_BOOTSTRAP__=") + len("window.__EIROS_BOOTSTRAP__=")
    boot = json.loads(html[start:html.index(";", start)])
    assert boot["requestedUri"] == claude_server.CLAUDE_PULSE_LEGACY_URI_V5


def test_corrupt_store_is_quarantined_not_erased():
    room_telemetry.record(widget_id="evidence", widget_kind="claude-pulse", status="first-tool-call:fail")
    room_telemetry.TELEMETRY_FILE.write_text("{broken json", encoding="utf-8")

    room_telemetry.record(widget_id="after", widget_kind="claude-pulse", status="html-parsed:ok")

    quarantined = sorted(room_telemetry.TELEMETRY_FILE.parent.glob(room_telemetry.TELEMETRY_FILE.name + ".corrupt-*"))
    assert quarantined, "the unreadable store was overwritten instead of moved aside"
    assert quarantined[-1].read_text(encoding="utf-8") == "{broken json"
    store = room_telemetry.read()
    assert store["recovered_from"] == quarantined[-1].name, "no pointer to where the evidence went"
    assert "after" in store["widgets"], "the channel did not recover"


def test_unmovable_unreadable_store_fails_closed(monkeypatch):
    room_telemetry.record(widget_id="evidence", widget_kind="claude-pulse", status="first-tool-call:fail")
    room_telemetry.TELEMETRY_FILE.write_text("{broken json", encoding="utf-8")
    monkeypatch.setattr(os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("read-only")))

    with pytest.raises(room_telemetry.TelemetryUnreadable):
        room_telemetry.record(widget_id="after", widget_kind="claude-pulse", status="html-parsed:ok")

    assert room_telemetry.TELEMETRY_FILE.read_text(encoding="utf-8") == "{broken json", (
        "the store was written even though it could not be read or moved aside"
    )


def test_a_parse_error_is_never_persisted_as_state():
    room_telemetry.TELEMETRY_FILE.write_text("[]", encoding="utf-8")
    room_telemetry.record(widget_id="after", widget_kind="claude-pulse", status="html-parsed:ok")
    assert "read_error" not in room_telemetry.read()


def test_boot_trace_rows_outlive_the_short_widget_retention():
    """A mount is read back long after it happened; room rows are not."""
    stale = int(__import__("time").time()) - (2 * room_telemetry.RETENTION_SECONDS)
    room_telemetry.record(widget_id="keep", widget_kind="claude-pulse", status="first-tool-call:fail")
    room_telemetry.record(widget_id="drop", widget_kind="room", status="ready")
    store = room_telemetry.read()
    for key in ("keep", "drop"):
        store["widgets"][key]["updated_at"] = stale
    room_telemetry._write(store)

    room_telemetry.record(widget_id="trigger", widget_kind="claude-pulse", status="html-parsed:ok")
    widgets = room_telemetry.read()["widgets"]
    assert "keep" in widgets, "boot-trace evidence was pruned on the short widget clock"
    assert "drop" not in widgets, "ordinary widget rows are no longer pruned"
