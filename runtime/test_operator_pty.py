import time

from runtime.vps_operator.pty import PtyManager


def _wait_for(mgr: PtyManager, session_id: str, needle: str, timeout: float = 3.0) -> str:
    deadline = time.time() + timeout
    out = ""
    seq = 0
    while time.time() < deadline and needle not in out:
        result = mgr.read(session_id, after_seq=seq)
        seq = result["seq"]
        out += result["data"]
        time.sleep(0.05)
    return out


def test_persistent_shell_write_read_and_close() -> None:
    mgr = PtyManager(max_buffer=65536)
    session = mgr.start("/bin/bash", cwd="/")
    sid = session["session_id"]
    mgr.write(sid, "printf 'PTY_OK\\n'\n")
    assert "PTY_OK" in _wait_for(mgr, sid, "PTY_OK")
    assert mgr.list()[0]["session_id"] == sid
    assert mgr.close(sid)["closed"] is True


def test_bounded_buffer_reports_truncation() -> None:
    mgr = PtyManager(max_buffer=256)
    session = mgr.start("/bin/bash", cwd="/")
    sid = session["session_id"]
    mgr.write(sid, "python3 -c \"print('X'*2000)\"\n")
    time.sleep(0.25)
    result = mgr.read(sid, after_seq=0, max_chars=128)
    assert len(result["data"]) <= 128
    assert result["truncated"] is True
    mgr.close(sid)
