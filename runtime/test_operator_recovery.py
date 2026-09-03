from pathlib import Path

from runtime.vps_operator.recovery import RecoveryManager


class FakeScheduler:
    def __init__(self):
        self.scheduled = []
        self.cancelled = []

    def schedule(self, tx_id, seconds):
        self.scheduled.append((tx_id, seconds))

    def cancel(self, tx_id):
        self.cancelled.append(tx_id)


def test_failed_verify_restores_original_file(tmp_path: Path) -> None:
    target = tmp_path / "config"
    target.write_text("good")
    target.chmod(0o640)
    scheduler = FakeScheduler()
    manager = RecoveryManager(tmp_path / "rb", scheduler=scheduler)
    tx = manager.stage([str(target)], seconds=30)["tx_id"]
    manager.atomic_write(tx, str(target), "bad", 0o600)
    assert target.read_text() == "bad"
    result = manager.verify(tx, ["/bin/false"])
    assert result["ok"] is False
    assert target.read_text() == "good"
    assert target.stat().st_mode & 0o777 == 0o640
    assert manager.status(tx)["state"] == "rolled_back"
    assert tx in scheduler.cancelled


def test_commit_cancels_rollback_and_keeps_new_file(tmp_path: Path) -> None:
    target = tmp_path / "config"
    target.write_text("old")
    scheduler = FakeScheduler()
    manager = RecoveryManager(tmp_path / "rb", scheduler=scheduler)
    tx = manager.stage([str(target)], seconds=45)["tx_id"]
    manager.atomic_write(tx, str(target), "new", 0o600)
    assert manager.verify(tx, ["/bin/true"])["ok"] is True
    assert manager.commit(tx)["state"] == "committed"
    assert target.read_text() == "new"
    assert scheduler.scheduled == [(tx, 45)]
    assert scheduler.cancelled[-1] == tx


def test_systemd_scheduler_requests_one_second_timer_accuracy(monkeypatch, tmp_path: Path) -> None:
    import runtime.vps_operator.recovery as recovery

    calls = []

    class Result:
        returncode = 0
        stdout = b""
        stderr = b""

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return Result()

    monkeypatch.setattr(recovery.subprocess, "run", fake_run)
    scheduler = recovery.SystemdScheduler(
        python=tmp_path / "python",
        script=tmp_path / "rollback.py",
    )
    scheduler.schedule("rb_test", 7)
    argv = calls[0][0]
    assert "--timer-property=AccuracySec=1s" in argv
