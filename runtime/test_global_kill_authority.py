from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run_node(script: str) -> None:
    result = subprocess.run(
        ["node", "-e", textwrap.dedent(script)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_legacy_global_kill_payloads_do_not_retire_listener() -> None:
    _run_node(
        r"""
        const { createPulseLifecycle } = require('./runtime/widget_lifecycle.js');
        const legacy = [
          JSON.stringify({generation:1, reason:'new-room-clean-start'}),
          JSON.stringify({generation:2, reason:'open_control_pill-ui-only'}),
          JSON.stringify({generation:3, reason:'open_widget_test kill-switch'}),
          'retired-by-old-card',
          '',
        ];
        for (const raw of legacy) {
          const listeners = {};
          const target = {
            addEventListener(name, fn) { listeners[name] = fn; },
            removeEventListener() {},
            localStorage: { setItem() {} },
          };
          const retired = [];
          createPulseLifecycle({
            target,
            projectId:'eiros-hub',
            threadId:'first-contact',
            sessionId:'new-listener',
            onRetire: reason => retired.push(reason),
          });
          listeners.storage({key:'eiros-ui-kill:eiros-hub:first-contact', newValue:raw});
          if (retired.length !== 0) {
            throw new Error('legacy/unknown global kill retired listener: '+raw);
          }
        }
        """
    )


def test_explicit_v2_global_kill_still_retires_listener() -> None:
    _run_node(
        r"""
        const { createPulseLifecycle } = require('./runtime/widget_lifecycle.js');
        const listeners = {};
        const target = {
          addEventListener(name, fn) { listeners[name] = fn; },
          removeEventListener() {},
          localStorage: { setItem() {} },
        };
        const retired = [];
        createPulseLifecycle({
          target,
          projectId:'eiros-hub',
          threadId:'first-contact',
          sessionId:'new-listener',
          onRetire: reason => retired.push(reason),
        });
        listeners.storage({
          key:'eiros-ui-kill:eiros-hub:first-contact',
          newValue:JSON.stringify({
            protocol:'eiros-global-kill-v2',
            authority:'operator-explicit',
            source:'close_eiros_widgets',
            generation:4,
            ts:5,
            reason:'manual close',
          }),
        });
        if (retired.join(',') !== 'global kill') {
          throw new Error('authorized global kill was not honored: '+retired.join(','));
        }
        """
    )


def test_listener_specific_kill_semantics_are_unchanged() -> None:
    _run_node(
        r"""
        const { createPulseLifecycle } = require('./runtime/widget_lifecycle.js');
        const listeners = {};
        const target = {
          addEventListener(name, fn) { listeners[name] = fn; },
          removeEventListener() {},
          localStorage: { setItem() {} },
        };
        const retired = [];
        createPulseLifecycle({
          target,
          projectId:'eiros-hub',
          threadId:'first-contact',
          sessionId:'new-listener',
          onRetire: reason => retired.push(reason),
        });
        listeners.storage({key:'eiros-wake-listener-kill:eiros-hub:first-contact', newValue:'anything'});
        if (retired.join(',') !== 'listener kill') {
          throw new Error('listener-specific kill semantics changed');
        }
        """
    )


def test_current_control_pill_source_never_broadcasts_global_kill() -> None:
    source = (ROOT / 'runtime/control_pill.html').read_text(encoding='utf-8')
    assert "localStorage.setItem(uiKillKey" not in source
    assert "open_control_pill-ui-only" not in source


def test_room_ignores_legacy_global_kill_and_requires_authorized_envelope() -> None:
    source = (ROOT / 'runtime/collab_room.html').read_text(encoding='utf-8')
    assert "isAuthorizedGlobalKill" in source
    assert "eiros-global-kill-v2" in source
    assert "operator-explicit" in source
    assert "source==='close_eiros_widgets'" in source or 'source==="close_eiros_widgets"' in source
    assert "if(e.key===killKey){if(isAuthorizedGlobalKill(e.newValue))stale();return}" in source


def test_killer_emits_authorized_v2_envelope() -> None:
    source = (ROOT / 'runtime/widget_killer.html').read_text(encoding='utf-8')
    assert "eiros-global-kill-v2" in source
    assert "operator-explicit" in source
    assert "close_eiros_widgets" in source


def test_listener_room_and_killer_use_fresh_cache_keys() -> None:
    from runtime import server_v2

    assert "pulse-anchor-v5-9" in server_v2.PULSE_SUM_URI
    assert server_v2.PULSE_SUM_VERSION.startswith("0.5.9-")
    assert "collab-room-v9-26" in server_v2.ROOM_URI
    assert server_v2.ROOM_VERSION.startswith("0.9.26-")
    assert "widget-killer-v2" in server_v2.UI_KILLER_URI
    rendered = server_v2._render_pulse_sum_html("mount-authorized-kill")
    assert "pulse-v59" in rendered
    assert "eiros-global-kill-v2" in rendered


def test_v59_has_a_fresh_canonical_mount_tool() -> None:
    from runtime import server_v2

    tools = server_v2.mcp._tool_manager._tools
    assert "open_pulse_v59" in tools
    tool = tools["open_pulse_v59"]
    assert tool.meta["ui"]["resourceUri"] == server_v2.PULSE_SUM_URI
    assert tool.meta["openai/outputTemplate"] == server_v2.PULSE_SUM_URI
    assert "open_pulse_v59 exactly once" in server_v2.mcp.instructions


def test_pulse_lite_also_ignores_legacy_global_kill() -> None:
    source = (ROOT / 'runtime/pulse_lite.html').read_text(encoding='utf-8')
    assert 'isAuthorizedGlobalKill' in source
    assert "eiros-global-kill-v2" in source
    assert "operator-explicit" in source
    assert "source==='close_eiros_widgets'" in source or 'source==="close_eiros_widgets"' in source
    assert "if(e.key===killKey&&isAuthorizedGlobalKill(e.newValue))" in source


def test_widget_test_diagnostic_cannot_broadcast_global_kill() -> None:
    source = (ROOT / 'runtime/server_v2.py').read_text(encoding='utf-8')
    assert "open_widget_test kill-switch" not in source
    assert "EIROS Kill Switch" not in source


def test_only_explicit_killer_source_writes_shared_global_kill() -> None:
    candidates = [
        ROOT / 'runtime/widget_killer.html',
        ROOT / 'runtime/control_pill.html',
        ROOT / 'runtime/collab_room.html',
        ROOT / 'runtime/pulse_lite.html',
        ROOT / 'runtime/pulse_anchor.html',
        ROOT / 'runtime/widget_lifecycle.js',
        ROOT / 'runtime/server_v2.py',
    ]
    writers = []
    for path in candidates:
        text = path.read_text(encoding='utf-8')
        if 'localStorage.setItem(killKey' in text or 'localStorage.setItem(uiKillKey' in text:
            writers.append(path.name)
    assert writers == ['widget_killer.html']
