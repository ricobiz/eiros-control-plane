from __future__ import annotations

import errno
import fcntl
import os
import pty
import signal as signal_module
import struct
import subprocess
import termios
import threading
import uuid
from collections import deque
from dataclasses import dataclass, field


@dataclass
class _Session:
    session_id: str
    master_fd: int
    proc: subprocess.Popen
    chunks: deque[tuple[int, bytes]] = field(default_factory=deque)
    buffered: int = 0
    seq: int = 0
    dropped_until_seq: int = 0
    lock: threading.RLock = field(default_factory=threading.RLock)


class PtyManager:
    def __init__(self, max_buffer: int = 1_000_000) -> None:
        self.max_buffer = max(1024, int(max_buffer)) if int(max_buffer) >= 1024 else int(max_buffer)
        self._sessions: dict[str, _Session] = {}
        self._lock = threading.RLock()

    def start(self, command: str = "/bin/bash", cwd: str = "/") -> dict[str, object]:
        master, slave = pty.openpty()
        proc = subprocess.Popen(
            command,
            shell=True,
            executable="/bin/bash",
            cwd=cwd,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            start_new_session=True,
            close_fds=True,
        )
        os.close(slave)
        sid = f"pty_{uuid.uuid4().hex}"
        session = _Session(sid, master, proc)
        with self._lock:
            self._sessions[sid] = session
        threading.Thread(target=self._reader, args=(session,), daemon=True, name=sid).start()
        return {
            "session_id": sid,
            "pid": proc.pid,
            "running": True,
            "cwd": cwd,
            "command_chars": len(str(command)),
        }

    def _reader(self, session: _Session) -> None:
        while True:
            try:
                data = os.read(session.master_fd, 8192)
            except OSError as exc:
                if exc.errno in {errno.EIO, errno.EBADF}:
                    break
                return
            if not data:
                break
            with session.lock:
                session.seq += 1
                session.chunks.append((session.seq, data))
                session.buffered += len(data)
                while session.buffered > self.max_buffer and session.chunks:
                    dropped_seq, dropped = session.chunks.popleft()
                    session.dropped_until_seq = max(session.dropped_until_seq, dropped_seq)
                    session.buffered -= len(dropped)

    def _get(self, session_id: str) -> _Session:
        with self._lock:
            session = self._sessions.get(str(session_id))
        if session is None:
            raise KeyError(f"PTY session not found: {session_id}")
        return session

    def write(self, session_id: str, data: str) -> dict[str, object]:
        session = self._get(session_id)
        payload = str(data).encode()
        written = 0
        while written < len(payload):
            written += os.write(session.master_fd, payload[written:])
        return {"session_id": str(session_id), "bytes": written}

    def read(self, session_id: str, after_seq: int = 0, max_chars: int = 200000) -> dict[str, object]:
        session = self._get(session_id)
        limit = max(1, min(int(max_chars), 200000))
        with session.lock:
            payload = b"".join(data for seq, data in session.chunks if seq > int(after_seq))
            truncated = int(after_seq) < session.dropped_until_seq or len(payload) > limit
            payload = payload[-limit:]
            code = session.proc.poll()
            return {
                "session_id": str(session_id),
                "seq": session.seq,
                "data": payload.decode("utf-8", "replace"),
                "running": code is None,
                "exit_code": code,
                "truncated": truncated,
            }

    def resize(self, session_id: str, rows: int, cols: int) -> dict[str, object]:
        session = self._get(session_id)
        fcntl.ioctl(
            session.master_fd,
            termios.TIOCSWINSZ,
            struct.pack("HHHH", int(rows), int(cols), 0, 0),
        )
        return {"session_id": str(session_id), "rows": int(rows), "cols": int(cols)}

    def signal(self, session_id: str, sig: int) -> dict[str, object]:
        session = self._get(session_id)
        os.killpg(os.getpgid(session.proc.pid), int(sig))
        return {"session_id": str(session_id), "signal": int(sig)}

    def close(self, session_id: str) -> dict[str, object]:
        session = self._get(session_id)
        if session.proc.poll() is None:
            try:
                os.killpg(os.getpgid(session.proc.pid), signal_module.SIGTERM)
                session.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(session.proc.pid), signal_module.SIGKILL)
                except ProcessLookupError:
                    pass
                session.proc.wait(timeout=2)
            except ProcessLookupError:
                pass
        try:
            os.close(session.master_fd)
        except OSError:
            pass
        with self._lock:
            self._sessions.pop(str(session_id), None)
        return {"session_id": str(session_id), "closed": True, "exit_code": session.proc.poll()}

    def list(self) -> list[dict[str, object]]:
        with self._lock:
            sessions = list(self._sessions.values())
        return [
            {
                "session_id": session.session_id,
                "pid": session.proc.pid,
                "running": session.proc.poll() is None,
                "seq": session.seq,
            }
            for session in sessions
        ]
