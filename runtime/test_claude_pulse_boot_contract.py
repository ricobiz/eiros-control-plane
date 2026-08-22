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
def test_previous_uris_still_serve_the_current_widget(uri_attr):
    """A bumped URI must not 404 the cards already mounted in someone's chat.

    Not asserting byte equality: each fetch opens its own mount row and stamps
    its own mountId into the bootstrap, so two fetches of the same resource are
    correctly different. What must hold is that a legacy URI serves the current
    widget rather than a stale one - the drift that turned WIDGET_TEST_LEGACY_URI
    into a dead card while its canonical twin became a live listener.
    """
    assert getattr(claude_server, uri_attr) != claude_server.CLAUDE_PULSE_URI
    suffix = uri_attr.split("_")[-1].lower()
    fn = getattr(claude_server, f"claude_pulse_resource_legacy_{suffix if suffix.startswith('v') else 'v4'}")
    legacy = fn()
    current = claude_server.claude_pulse_resource()

    def boot_of(html):
        start = html.index("window.__EIROS_BOOTSTRAP__=") + len("window.__EIROS_BOOTSTRAP__=")
        return json.loads(html[start:html.index(";", start)])

    legacy_boot, current_boot = boot_of(legacy), boot_of(current)
    assert legacy_boot["pulseVersion"] == current_boot["pulseVersion"] == claude_server.CLAUDE_PULSE_VERSION
    assert legacy_boot["agentId"] == current_boot["agentId"]
    assert legacy_boot["mountId"] != current_boot["mountId"], "two fetches shared one mount row"

    # requestedUri is supposed to differ - that is the diagnostic-integrity fix:
    # the widget now reports which URI actually served it, so a legacy fetch
    # cannot be mistaken for a canonical one. mountId differs for the same
    # reason each fetch opens its own row. Strip both, then the two documents
    # must be the same widget otherwise.
    assert legacy_boot["requestedUri"] == getattr(claude_server, uri_attr)
    assert current_boot["requestedUri"] == claude_server.CLAUDE_PULSE_URI

    def strip(html, boot):
        return html.replace(boot["mountId"], "").replace(boot["requestedUri"], "")

    assert strip(legacy, legacy_boot) == strip(current, current_boot), (
        "the legacy URI serves different markup than the canonical one"
    )


def test_sdk_import_pins_zod():
    """Unpinned, the App SDK cannot load in a browser at all.

    esm.sh resolves @modelcontextprotocol/sdk's zod dependency to a major that
    no longer exports z.custom, which the SDK calls at module scope. Every
    unpinned specifier throws "t.custom is not a function" before App is
    reachable, so app.sendMessage() has never run. Verified in headless
    Chromium against @1.1.2, @1.1.0, @1.0.0 and the floating tag; ?deps=zod@3
    loads and exposes App. Dropping the pin silently disables the wake path.
    """
    urls = re.findall(r"'(https://esm\.sh/@modelcontextprotocol/ext-apps[^']*)'", HTML)
    assert urls, "no App SDK import left in the widget"
    for url in urls:
        assert "deps=zod@3" in url, f"unpinned SDK specifier would fail to load: {url}"


def test_sdk_connect_cannot_hang_forever():
    """A host that never answers initialize must not strand the only wake path."""
    assert "App.connect() timed out" in HTML, "no timeout guarding App.connect()"
    assert "Promise.race" in HTML


def test_a_failed_wake_is_retried_rather_than_recorded_as_sent():
    """lastEmitted must only advance once some path actually took the wake."""
    assert "lastEmitted=mid" not in HTML.replace("if(delivered)lastEmitted=mid", ""), (
        "the message is marked emitted before the wake resolves, so a transient "
        "failure drops that wake permanently"
    )
    assert "if(delivered)lastEmitted=mid" in HTML


def test_status_does_not_claim_delivery_before_the_wake_resolves():
    assert "Waking Claude for" in HTML, "no in-flight status; the panel claims success too early"
