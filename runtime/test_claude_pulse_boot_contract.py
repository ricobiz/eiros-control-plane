"""The Claude Pulse widget must stay diagnosable.

Its predecessor only heartbeat after a successful dialog_peek, so a widget that
died on its first tool call registered no session at all and left the failure
indistinguishable from never having mounted. agent_id=claude has exactly one
session in the whole history of the deployment, which is why this matters.
"""
from __future__ import annotations

import json
import re

import pytest

from runtime import claude_server

HTML = claude_server.CLAUDE_PULSE_HTML.read_text(encoding="utf-8")
REQUIRED_STAGES = {
    "html-parsed",
    "host-bridge",
    "first-tool-call",
    "sdk-import",
    "sdk-connect",
    "dialog-peek",
    "wake-sdk",
    "wake-raw-fallback",
}


def test_every_boot_stage_is_reported():
    declared = set(re.findall(r"stage\('([a-z-]+)'", HTML))
    missing = REQUIRED_STAGES - declared
    assert not missing, f"boot stages no longer reported: {sorted(missing)}"


def test_heartbeat_is_attempted_before_the_first_read():
    """Presence must be proven before anything that can fail silently."""
    first_call = HTML.index("stage('first-tool-call'")
    first_peek = HTML.index("stage('dialog-peek'")
    assert first_call < first_peek, "dialog_peek is instrumented before the proving heartbeat"
    assert "room_heartbeat" in HTML[:first_peek], "no heartbeat before the first read"


def test_widget_reports_through_two_independent_channels():
    assert "room_telemetry_update" in HTML, "no server-side readout"
    assert "paintLadder" in HTML, "no on-screen readout for when tool calls fail"


def test_raw_postmessage_fallback_is_not_reported_as_delivered():
    """postMessage is fire-and-forget; claiming success there would be a lie."""
    block = HTML[HTML.index("wake-raw-fallback"):]
    settle = re.search(r"settle\(raw,'([a-z]+)'", block)
    assert settle, "raw fallback never settles its stage"
    assert settle.group(1) != "ok", "raw ui/message must not be recorded as confirmed delivery"


def test_resource_substitutes_bootstrap_and_identifies_claude():
    html = claude_server.claude_pulse_resource()
    assert "__EIROS_BOOTSTRAP_JSON__" not in html
    start = html.index("window.__EIROS_BOOTSTRAP__=") + len("window.__EIROS_BOOTSTRAP__=")
    boot = json.loads(html[start:html.index(";", start)])
    assert boot["agentId"] == "claude"
    assert boot["projectId"] and boot["threadId"]
    assert boot["pulseVersion"] == claude_server.CLAUDE_PULSE_VERSION


@pytest.mark.parametrize("uri_attr", ["CLAUDE_PULSE_LEGACY_URI_V5", "CLAUDE_PULSE_LEGACY_URI", "CLAUDE_PULSE_LEGACY_URI_V3"])
def test_previous_uris_still_resolve(uri_attr):
    """A bumped URI must not 404 the cards already mounted in someone's chat."""
    assert getattr(claude_server, uri_attr) != claude_server.CLAUDE_PULSE_URI
    suffix = uri_attr.split("_")[-1].lower()
    fn = getattr(claude_server, f"claude_pulse_resource_legacy_{suffix if suffix.startswith('v') else 'v4'}")
    assert fn() == claude_server.claude_pulse_resource()
