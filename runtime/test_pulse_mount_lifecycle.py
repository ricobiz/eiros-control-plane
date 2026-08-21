from __future__ import annotations

import json
from pathlib import Path
import subprocess
import textwrap
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class PulseMountLifecycleTests(unittest.TestCase):
    def test_sibling_iframe_does_not_retire_visible_pulse(self) -> None:
        script = textwrap.dedent(
            """
            const { createPulseLifecycle } = require('./runtime/widget_lifecycle.js');

            const listeners = {};
            const writes = [];
            const target = {
              addEventListener(name, fn) { listeners[name] = fn; },
              removeEventListener(name, fn) {
                if (listeners[name] === fn) delete listeners[name];
              },
            };
            const storage = {
              setItem(key, value) { writes.push([key, value]); },
            };
            target.localStorage = storage;
            const retirements = [];
            const lifecycle = createPulseLifecycle({
              target,
              projectId: 'eiros-hub',
              threadId: 'first-contact',
              sessionId: 'visible-card',
              onRetire: reason => retirements.push(reason),
            });

            lifecycle.retireLegacy([
              'eiros-wake-listener-active-v49:eiros-hub:first-contact:chatgpt:chatgpt-main',
            ]);
            listeners.storage({
              key: 'eiros-wake-listener-active-v55:eiros-hub:first-contact:chatgpt:chatgpt-main',
              newValue: 'hidden-preflight-frame',
            });
            if (retirements.length !== 0) {
              throw new Error('a sibling iframe retired the visible Pulse');
            }
            if (writes.length !== 1 || !writes[0][1].includes('visible-card')) {
              throw new Error('legacy Pulse was not retired by this session');
            }

            listeners.storage({
              key: 'eiros-ui-kill:eiros-hub:first-contact',
              newValue: 'operator-kill',
            });
            if (retirements.join(',') !== 'global kill') {
              throw new Error('global killer did not retire Pulse exactly once');
            }
            """
        )
        result = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_denied_browser_storage_does_not_crash_lifecycle(self) -> None:
        script = textwrap.dedent(
            """
            const { createPulseLifecycle } = require('./runtime/widget_lifecycle.js');

            const listeners = {};
            const target = {
              addEventListener(name, fn) { listeners[name] = fn; },
              removeEventListener(name, fn) {
                if (listeners[name] === fn) delete listeners[name];
              },
            };
            Object.defineProperty(target, 'localStorage', {
              get() { throw new Error('SecurityError: storage denied'); },
            });

            const retirements = [];
            const lifecycle = createPulseLifecycle({
              target,
              projectId: 'eiros-hub',
              threadId: 'first-contact',
              sessionId: 'storage-denied-card',
              onRetire: reason => retirements.push(reason),
            });

            lifecycle.retireLegacy([
              'eiros-wake-listener-active-v49:eiros-hub:first-contact:chatgpt:chatgpt-main',
            ]);
            listeners.storage({
              key: 'eiros-ui-kill:eiros-hub:first-contact',
              newValue: 'operator-kill',
            });
            if (retirements.join(',') !== 'global kill') {
              throw new Error('lifecycle did not survive denied browser storage');
            }
            """
        )
        result = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_current_and_handoff_pulse_generations_can_poll(self) -> None:
        from runtime import server_v2

        with (
            patch.object(
                server_v2.event_engine,
                "poll",
                return_value={
                    "ok": True,
                    "disabled": False,
                    "leader": True,
                    "event": None,
                    "events": [],
                    "cursor": 0,
                },
            ) as poll,
            patch.object(server_v2, "_observe_widget_pair", return_value={}),
        ):
            for widget_id in ("pulse-v55-handoff", "pulse-v56-current"):
                with self.subTest(widget_id=widget_id):
                    result = server_v2.pulse_poll(widget_id=widget_id)
                    self.assertFalse(result.get("disabled"), result)
            self.assertEqual(poll.call_count, 2)

    def test_open_pulse_returns_small_non_idempotent_mount_envelope(self) -> None:
        from runtime import server_v2

        with (
            patch.object(server_v2.collab_engine, "session_heartbeat"),
            patch.object(
                server_v2,
                "build_resume_context",
                return_value={"resume_required": False},
            ),
            patch.object(
                server_v2.event_engine,
                "status",
                return_value={"pending_count": 0, "latest_seq": 0},
            ),
        ):
            result = server_v2.open_pulse()
        encoded = json.dumps(result, ensure_ascii=False).encode("utf-8")
        tool = server_v2.mcp._tool_manager._tools["open_pulse"]

        self.assertLess(len(encoded), 4096)
        self.assertNotIn("widget_blackbox", result)
        self.assertIs(tool.annotations.idempotentHint, False)

    def test_rendered_pulse_embeds_lifecycle_controller(self) -> None:
        from runtime import server_v2

        rendered = server_v2.pulse_anchor_resource()

        self.assertIn("createPulseLifecycle", rendered)
        self.assertNotIn("__EIROS_WIDGET_LIFECYCLE_JS__", rendered)
        self.assertNotIn("storage:localStorage", rendered)
        self.assertIn("sessionPrefix", rendered)
        self.assertIn("pulse-v56", rendered)
        self.assertIn("0.5.6-storage-safe-host-pip", rendered)


if __name__ == "__main__":
    unittest.main()
