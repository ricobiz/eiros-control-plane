from pathlib import Path

from runtime.vps_operator.desktop import DesktopController
from runtime.vps_operator.secrets import SecretStore


class FakeBackend:
    def __init__(self):
        self.events = []
    def capture_jpeg(self, region=None):
        return b"frame", (1440, 900)
    def windows(self):
        return []
    def focus(self, window_id):
        pass
    def run_input(self, argv, stdin=None):
        self.events.append((tuple(argv), stdin))
    def clipboard_set(self, payload):
        pass


def test_store_permissions_and_redacted_metadata(tmp_path: Path) -> None:
    root = tmp_path / "secrets"
    store = SecretStore(root)
    result = store.set("broker_password", "s3cr3t")
    assert result == {"ok": True, "name": "broker_password", "bytes": 6}
    assert root.stat().st_mode & 0o777 == 0o700
    assert (root / "broker_password").stat().st_mode & 0o777 == 0o600
    assert "s3cr3t" not in repr(store.list())
    assert store.exists("broker_password")["exists"] is True


def test_type_secret_uses_desktop_stdin_and_not_argv(tmp_path: Path) -> None:
    store = SecretStore(tmp_path / "secrets")
    store.set("broker_password", "s3cr3t")
    backend = FakeBackend()
    desktop = DesktopController(backend=backend)
    result = store.type_into_desktop("broker_password", desktop)
    argv, stdin = backend.events[-1]
    assert result == {"ok": True, "name": "broker_password", "bytes": 6}
    assert argv[-2:] == ("--file", "-")
    assert "s3cr3t" not in " ".join(argv)
    assert stdin == b"s3cr3t"
    assert "s3cr3t" not in repr(result)


def test_process_output_is_redacted_even_if_child_echoes_secret(tmp_path: Path) -> None:
    store = SecretStore(tmp_path / "secrets")
    store.set("broker_password", "s3cr3t")
    env_result = store.run_with_env(
        {"BROKER_PASS": "broker_password"},
        ["/bin/sh", "-c", 'printf %s "$BROKER_PASS"'],
    )
    stdin_result = store.run_with_stdin("broker_password", ["/bin/cat"])
    assert env_result["ok"] is True
    assert env_result["stdout"] == "***REDACTED***"
    assert stdin_result["stdout"] == "***REDACTED***"
    assert "s3cr3t" not in repr(env_result)
    assert "s3cr3t" not in repr(stdin_result)
