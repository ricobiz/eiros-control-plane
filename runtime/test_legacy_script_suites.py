"""Run legacy script-style `test_*.py` files that pytest silently ignores.

runtime/ contains legacy script-style test_* files whose assertions
between them and contribute exactly zero to every green run: they were written
as standalone scripts with a `main()` under `if __name__ == "__main__"`, and no
`def test_*` or `class Test*` for pytest to collect. `pytest -q` prints a
passing count that has never included any of them, which is worse than having
no tests at all - the number looks like coverage and is not.

Rather than rewrite 117 assertions (churn, and a chance to change behaviour
while "only" reformatting), each script is executed here as a subprocess and
its exit code is the assertion. They stay runnable by hand exactly as before,
and a green pytest run now actually means they passed.

New tests should be written as ordinary pytest functions; this shim exists for
what is already here, not as a pattern to follow.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

CODE_ROOT = Path(__file__).resolve().parents[1]

SCRIPT_SUITES = [
    "test_companion",
    "test_foundation",
    "test_installer",
    "test_pip_controller",
    "test_pulse_mount_lifecycle",
    "test_queue",
    "test_root_broker",
    "test_sam",
    "test_scheduler",
    "test_security",
    "test_snapshot",
    "test_ui_contract",
    "test_watchdog",
]

# Suites that fail against current main for a real, already-reported defect
# rather than test rot. strict=True on purpose: the day the defect is fixed
# this turns red and the entry has to be removed, so the list cannot quietly
# become a place where failures go to be forgotten.
KNOWN_BROKEN: dict[str, str] = {}


def _is_script_suite(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    has_pytest_entrypoints = "\ndef test_" in text or text.startswith("def test_") or "\nclass Test" in text
    return "__main__" in text and not has_pytest_entrypoints


def test_the_script_suite_list_is_still_accurate():
    """Guard the guard: a new uncollected test_* file must not slip in unnoticed."""
    on_disk = {
        path.stem
        for path in sorted(CODE_ROOT.glob("runtime/test_*.py"))
        if path.stem != Path(__file__).stem and _is_script_suite(path)
    }
    assert on_disk == set(SCRIPT_SUITES), (
        "uncollected script-style test files changed; "
        f"missing from the list: {sorted(on_disk - set(SCRIPT_SUITES))}, "
        f"listed but no longer script-style: {sorted(set(SCRIPT_SUITES) - on_disk)}"
    )


@pytest.mark.parametrize("suite", SCRIPT_SUITES)
def test_script_suite_exits_clean(suite, request):
    if suite in KNOWN_BROKEN:
        request.applymarker(pytest.mark.xfail(reason=KNOWN_BROKEN[suite], strict=True))
    data_dir = Path(tempfile.mkdtemp(prefix=f"eiros-{suite}-"))
    (data_dir / "runtime").mkdir(parents=True, exist_ok=True)
    config_dir = data_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    for example in (CODE_ROOT / "config").glob("*.example.json"):
        (config_dir / example.name.replace(".example.json", ".json")).write_bytes(example.read_bytes())

    env = dict(os.environ, EIROS_DATA_DIR=str(data_dir), PYTHONPATH=str(CODE_ROOT))
    result = subprocess.run(
        [sys.executable, str(CODE_ROOT / "runtime" / f"{suite}.py")],
        cwd=str(CODE_ROOT), env=env, capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, (
        f"{suite}.py exited {result.returncode}\n"
        f"--- stdout ---\n{result.stdout[-4000:]}\n--- stderr ---\n{result.stderr[-4000:]}"
    )
