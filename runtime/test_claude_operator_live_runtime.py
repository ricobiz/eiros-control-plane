from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import subprocess

ROOT = Path('/opt/eiros-control-plane')
# LIVE_SERVER must be the exact module deploy/claude_operator_runtime.py imports at
# runtime (`from runtime import server_v2 as live_server`, resolved from ROOT via
# sys.path - see that file's own top-of-file comment). It previously pointed at
# .worktrees/sum-auto-wake/runtime/server_v2.py, a frozen copy that stopped being
# live once feat/sum-auto-wake merged; that let this test silently drift from
# reality depending on unrelated worktree state elsewhere on the box (see
# project_state.flaky_test_live_operator_runtime_2026_08_24). Do not repoint this
# at any worktree-scoped path again - test_live_server_path_is_not_worktree_scoped
# below guards exactly that.
LIVE_SERVER = ROOT / 'runtime/server_v2.py'
MAIN_VPS_OPS = ROOT / 'runtime/vps_ops_server.py'
RUNNER = Path('deploy/claude_operator_runtime.py')


def _decorated_tool_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding='utf-8'))
    names: set[str] = set()
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for deco in node.decorator_list:
            text = ast.unparse(deco)
            if not text.startswith('mcp.tool'):
                continue
            name = node.name
            if isinstance(deco, ast.Call):
                for kw in deco.keywords:
                    if kw.arg == 'name' and isinstance(kw.value, ast.Constant):
                        name = str(kw.value.value)
            names.add(name)
    return names


def test_live_operator_runtime_exposes_live_ebridge_plus_latest_vps_ops() -> None:
    assert RUNNER.exists(), 'deploy/claude_operator_runtime.py is missing'
    env = dict(os.environ)
    env['EIROS_DATA_DIR'] = str(ROOT)
    proc = subprocess.run(
        ['/opt/eiros-control-plane/venv/bin/python', str(RUNNER), '--list-tools'],
        text=True,
        capture_output=True,
        timeout=30,
        env=env,
        check=True,
    )
    actual = set(json.loads(proc.stdout))
    expected = _decorated_tool_names(LIVE_SERVER) | _decorated_tool_names(MAIN_VPS_OPS)
    assert actual == expected, {
        'missing': sorted(expected - actual),
        'unexpected': sorted(actual - expected),
    }


def test_live_server_path_is_not_worktree_scoped() -> None:
    assert '.worktrees' not in str(LIVE_SERVER), (
        'LIVE_SERVER must track the main checkout that deploy/claude_operator_runtime.py '
        'actually imports at runtime, not a frozen worktree snapshot - see '
        'project_state.flaky_test_live_operator_runtime_2026_08_24'
    )


def test_operator_service_runs_live_runtime_runner() -> None:
    service = Path('deploy/eiros-claude-operator.service').read_text(encoding='utf-8')
    assert 'Environment=EIROS_DATA_DIR=/opt/eiros-control-plane' in service
    assert 'deploy/claude_operator_runtime.py' in service


def test_operator_allows_claude_web_origins_without_disabling_rebinding_protection() -> None:
    text = RUNNER.read_text(encoding='utf-8')
    assert 'TransportSecuritySettings' in text
    assert 'enable_dns_rebinding_protection=True' in text
    assert 'https://claude.ai' in text
    assert 'https://claude.com' in text
