from pathlib import Path
import json

from runtime.operator.audit import AuditLog
from runtime.operator.files import RootFiles


def test_root_files_can_write_read_replace_and_delete_outside_repo(tmp_path: Path) -> None:
    root = RootFiles()
    path = tmp_path / "nested" / "state.txt"
    root.write_atomic(str(path), "alpha", mode=0o640)
    assert root.read(str(path), max_bytes=100)["content"] == "alpha"
    assert root.stat(str(path))["mode"] == "0640"
    root.replace(str(path), "alpha", "beta", count=1)
    assert path.read_text() == "beta"
    root.delete(str(path), recursive=False)
    assert not path.exists()


def test_audit_never_serializes_secret_fields(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    audit = AuditLog(path)
    audit.write("secret_type", True, {"secret_name": "broker", "password": "DO_NOT_LOG"}, 7)
    raw = path.read_text()
    assert "DO_NOT_LOG" not in raw
    event = json.loads(raw)
    assert event["target"]["secret_name"] == "broker"
    assert "password" not in event["target"]
