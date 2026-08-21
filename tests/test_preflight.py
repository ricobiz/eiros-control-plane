import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from deploy import preflight


def _exec_start(argv: str) -> str:
    return "{ path=/x ; argv[]=" + argv + " ; ignore_errors=no ; start_time=[n/a] }"


def test_parses_module_entrypoint():
    argv = preflight.parse_exec_start(
        _exec_start("/opt/eiros-control-plane/venv/bin/python -m runtime.sam daemon")
    )
    assert argv[-2:] == ["runtime.sam", "daemon"]
    assert preflight.import_target(argv) == ("module", "runtime.sam")


def test_parses_uvicorn_app_entrypoint():
    argv = preflight.parse_exec_start(
        _exec_start(
            "/opt/eiros-control-plane/venv/bin/uvicorn runtime.companion_server:app"
            " --host 127.0.0.1 --port 8791 --workers 1"
        )
    )
    assert preflight.import_target(argv) == ("module", "runtime.companion_server")


def test_parses_script_entrypoint():
    argv = preflight.parse_exec_start(
        _exec_start("/opt/eiros-control-plane/venv/bin/python deploy/claude_operator_runtime.py")
    )
    assert preflight.import_target(argv) == ("file", "deploy/claude_operator_runtime.py")


def test_skips_non_python_entrypoint():
    argv = preflight.parse_exec_start(_exec_start("/usr/local/bin/tunnel-client run --profile eiros"))
    assert preflight.import_target(argv) is None


def test_skips_inline_program():
    argv = preflight.parse_exec_start(_exec_start("/usr/bin/python3 -c 'import runtime.x'"))
    assert preflight.import_target(argv) is None


def test_environment_overlays_unit_values():
    env = preflight.environment({"Environment": "PYTHONPATH=/srv/app EIROS_DATA_DIR=/srv/data"})
    assert env["PYTHONPATH"] == "/srv/app"
    assert env["EIROS_DATA_DIR"] == "/srv/data"


def test_transient_bootstrap_units_are_skipped():
    assert "eiros-claude-bootstrap.service".startswith(preflight.SKIP_PREFIXES)
    assert "eiros-claude-op-bootstrap-clean-1787325987.service".startswith(preflight.SKIP_PREFIXES)
    assert not "eiros-sam.service".startswith(preflight.SKIP_PREFIXES)
