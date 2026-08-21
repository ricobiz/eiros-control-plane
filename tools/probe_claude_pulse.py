"""Drive the Claude Pulse widget in a real browser against mock MCP hosts.

The widget cannot be verified where it actually runs - that needs Rico's
claude.ai session - so the next best thing is to prove that given a working
host it behaves correctly, and that given each way a host can fail it says so.
Then a failure in the live mount is attributable to the host rather than to us.

Run:  venv/bin/python tools/probe_claude_pulse.py
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_ROOT))

# The probe is a test harness, not a deployment client. Never require or mutate
# the checkout's live config just to import claude_server. Seed the same example
# config that pytest uses into a throwaway data directory.
if os.environ.get("EIROS_PROBE_ALLOW_LIVE_DATA_DIR", "").strip().lower() not in {"1", "true", "yes"}:
    _probe_data = Path(tempfile.mkdtemp(prefix="eiros-claude-pulse-probe-"))
    (_probe_data / "config").mkdir(parents=True, exist_ok=True)
    (_probe_data / "runtime").mkdir(parents=True, exist_ok=True)
    for _example in (CODE_ROOT / "config").glob("*.example.json"):
        shutil.copyfile(_example, _probe_data / "config" / _example.name.replace(".example.json", ".json"))
    os.environ["EIROS_DATA_DIR"] = str(_probe_data)

from playwright.async_api import async_playwright  # noqa: E402

import runtime.claude_server as claude_server  # noqa: E402

PARENT_HTML = """<!doctype html><html><body>
<script>
window.__calls = [];
window.__mode = "MODE";
function reply(id, result, error){
  const frame = document.getElementById('w').contentWindow;
  frame.postMessage(error ? {jsonrpc:'2.0', id, error:{message:error}} : {jsonrpc:'2.0', id, result}, '*');
}
window.addEventListener('message', ev => {
  const m = ev.data || {};
  if (m.jsonrpc !== '2.0') return;
  if (m.method === 'tools/call') {
    window.__calls.push({name: m.params.name, args: m.params.arguments});
    if (window.__mode === 'reject-all') return reply(m.id, null, 'Connector not found');
    if (m.params.name === 'dialog_peek') return reply(m.id, {structuredContent: window.__peek});
    return reply(m.id, {structuredContent: {ok: true}});
  }
  if (m.method === 'ui/message') { window.__uiMessages = window.__uiMessages || []; window.__uiMessages.push(m.params); }
  if (m.method === 'eiros/test-sdk-sendMessage') { window.__sdkMessages = window.__sdkMessages || []; window.__sdkMessages.push(m.params); }
});
</script>
<iframe id="w" style="width:420px;height:640px;border:0"></iframe>
</body></html>"""


async def run_case(browser, name, *, mode, native_bridge, peek, settle_seconds=4.0, fake_sdk=False):
    page = await browser.new_page()
    await page.set_content(PARENT_HTML.replace('"MODE"', json.dumps(mode)))
    await page.evaluate("p => { window.__peek = p }", peek)

    widget_html = claude_server.claude_pulse_resource()
    if fake_sdk:
        # Isolate our success-path logic from the real CDN/host handshake: the
        # separate root-cause probe proves the pinned SDK can import. Here we
        # prove that once App is available, connect + sendMessage is used once
        # and the raw ui/message fallback is not touched.
        sdk_shim = """<script>
        window.__EIROS_APP_SDK__ = { App: class {
          constructor(meta){ this.meta = meta; }
          async connect(){ return true; }
          async sendMessage(message){
            window.parent.postMessage({jsonrpc:'2.0', method:'eiros/test-sdk-sendMessage', params:message}, '*');
            return true;
          }
        }};
        </script>"""
        widget_html = widget_html.replace("<body>", "<body>" + sdk_shim, 1)
    if native_bridge:
        # A host that exposes window.mcp.callTool directly, the way the real
        # app bridge does, instead of leaving the widget on raw postMessage.
        shim = """<script>
        window.mcp = { callTool: (n, a) => new Promise((res, rej) => {
          const id = 'native-' + Math.random();
          const h = e => { const m = e.data||{}; if (m.id !== id) return;
            window.removeEventListener('message', h);
            m.error ? rej(new Error(m.error.message)) : res(m.result); };
          window.addEventListener('message', h);
          window.parent.postMessage({jsonrpc:'2.0', id, method:'tools/call', params:{name:n, arguments:a}}, '*');
        })};
        </script>"""
        widget_html = widget_html.replace("<body>", "<body>" + shim, 1)

    await page.evaluate(
        "html => { document.getElementById('w').srcdoc = html }", widget_html
    )
    frame_el = await page.query_selector("#w")
    frame = await frame_el.content_frame()
    await asyncio.sleep(settle_seconds)

    ladder = await frame.evaluate(
        "() => Array.from(document.querySelectorAll('#ladder div')).map(d => d.textContent.trim())"
    )
    status = await frame.evaluate("() => document.getElementById('status').textContent")
    calls = await page.evaluate("() => window.__calls.map(c => c.name)")
    ui_messages = await page.evaluate("() => (window.__uiMessages||[]).length")
    sdk_messages = await page.evaluate("() => (window.__sdkMessages||[]).length")
    await page.close()
    return {"case": name, "ladder": ladder, "status": status, "calls": calls, "ui_messages": ui_messages, "sdk_messages": sdk_messages}


def check(result, *, expect_first_call, expect_order, expect_ui_messages=None, expect_sdk_messages=None, expect_contains=(), expect_absent=()):
    problems = []
    calls = [c for c in result["calls"] if c != "room_telemetry_update"]
    if expect_first_call and (not calls or calls[0] != expect_first_call):
        problems.append(f"first non-telemetry call was {calls[:1]}, expected {expect_first_call!r}")
    text = " | ".join(result["ladder"])
    for earlier, later in expect_order:
        if earlier not in text or later not in text:
            problems.append(f"missing stage(s): {earlier!r} / {later!r}")
        elif text.index(earlier) > text.index(later):
            problems.append(f"{earlier!r} reported after {later!r}")
    if expect_ui_messages is not None and result["ui_messages"] != expect_ui_messages:
        problems.append(f"ui/message count {result['ui_messages']}, expected {expect_ui_messages}")
    if expect_sdk_messages is not None and result["sdk_messages"] != expect_sdk_messages:
        problems.append(f"SDK sendMessage count {result['sdk_messages']}, expected {expect_sdk_messages}")
    for token in expect_contains:
        if token not in text:
            problems.append(f"missing ladder token {token!r}")
    for token in expect_absent:
        if token in text:
            problems.append(f"unexpected ladder token {token!r}")
    return problems


async def main() -> int:
    empty = {"messages": [], "pending_count": 0}
    waiting = {"messages": [{"message_id": "m1", "seq": 42, "from_agent": "chatgpt",
                             "content": "probe", "project_id": "eiros-hub",
                             "thread_id": "first-contact"}], "pending_count": 1}
    failures = 0
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        cases = [
            ("healthy host, native bridge", dict(mode="ok", native_bridge=True, peek=empty),
             dict(expect_first_call="room_heartbeat",
                  expect_order=[("html-parsed", "first-tool-call"), ("first-tool-call", "dialog-peek")])),
            ("message waiting, SDK sendMessage succeeds",
             dict(mode="ok", native_bridge=True, peek=waiting, fake_sdk=True, settle_seconds=5.0),
             dict(expect_first_call="room_heartbeat",
                  expect_order=[("first-tool-call", "dialog-peek"), ("dialog-peek", "wake-sdk")],
                  expect_ui_messages=0, expect_sdk_messages=1,
                  expect_contains=("✓wake-sdk", "✓sdk-connect"),
                  expect_absent=("wake-raw-fallback",))),
            ("healthy host, postMessage only", dict(mode="ok", native_bridge=False, peek=empty),
             dict(expect_first_call="room_heartbeat",
                  expect_order=[("html-parsed", "first-tool-call"), ("first-tool-call", "dialog-peek")])),
            ("host rejects every tool call", dict(mode="reject-all", native_bridge=True, peek=empty),
             dict(expect_first_call="room_heartbeat",
                  expect_order=[("html-parsed", "first-tool-call")])),
            # Long enough to pass the 8s App.connect() timeout: the mock parent
            # never answers the MCP UI handshake, which is exactly the "host
            # goes silent" case the raw fallback exists for.
            ("message waiting, host never completes SDK handshake",
             dict(mode="ok", native_bridge=True, peek=waiting, settle_seconds=13.0),
             dict(expect_first_call="room_heartbeat",
                  expect_order=[("first-tool-call", "dialog-peek"), ("dialog-peek", "wake-sdk"),
                                ("wake-sdk", "wake-raw-fallback")],
                  expect_ui_messages=1)),
        ]
        for name, kwargs, expectations in cases:
            result = await run_case(browser, name, **kwargs)
            problems = check(result, **expectations)
            print(f"\n=== {name} ===")
            for line in result["ladder"]:
                print("   ", line)
            print("    calls:", result["calls"])
            print("    ui/message delivered to parent:", result["ui_messages"])
            print("    SDK sendMessage delivered to parent:", result["sdk_messages"])
            print("    status:", " ".join(result["status"].split())[:160])
            if problems:
                failures += 1
                for p in problems:
                    print("    PROBLEM:", p)
            else:
                print("    OK")
        await browser.close()
    print("\nfailures:", failures)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
