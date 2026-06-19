from __future__ import annotations

import json
from typing import Any

from root.root_broker import handle_request


def fake_runner(command: list[str], timeout: int) -> dict[str, Any]:
    return {"ok": True, "exit_code": 0, "stdout": " ".join(command), "stderr": "", "timeout": timeout}


def main() -> None:
    checks: list[str] = []

    status = handle_request({"op": "status", "request_id": "status-test"}, fake_runner)
    assert status["ok"] and status["request_id"] == "status-test"
    checks.append("status")

    service = handle_request({"op": "service_status", "service": "eiros-worker.service"}, fake_runner)
    assert service["ok"] and "systemctl show eiros-worker.service" in service["stdout"]
    checks.append("allowed service status")

    restart = handle_request({"op": "service_restart", "service": "eiros-tunnel.service", "reason": "test"}, fake_runner)
    assert restart["ok"] and restart["reason"] == "test"
    checks.append("audited restart contract")

    try:
        handle_request({"op": "service_restart", "service": "ssh.service", "reason": "bad"}, fake_runner)
        raise AssertionError("disallowed service accepted")
    except ValueError as exc:
        assert "not allowed" in str(exc)
    checks.append("service allowlist")

    try:
        handle_request({"op": "service_restart", "service": "eiros-worker.service", "reason": ""}, fake_runner)
        raise AssertionError("empty reason accepted")
    except ValueError as exc:
        assert "reason" in str(exc)
    checks.append("restart reason required")

    try:
        handle_request({"op": "exec", "command": "id"}, fake_runner)
        raise AssertionError("arbitrary exec accepted")
    except ValueError as exc:
        assert "Unsupported" in str(exc)
    checks.append("arbitrary shell rejected")

    print(json.dumps({"ok": True, "checks": checks, "count": len(checks)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
