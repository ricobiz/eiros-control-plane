# EIROS Full VPS Operator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give EIROS end-to-end control of the dedicated EBRIDGE VPS: unrestricted root/filesystem operations, a model-visible/control-capable `DISPLAY=:99`, persistent root PTYs, local secret injection, and rollback-protected critical changes, then prove it by logging into IC Markets MT5 without Rico operating noVNC.

**Architecture:** Extend the existing privileged `runtime/vps_ops_server.py` surface mirrored by `deploy/claude_operator_runtime.py`. Keep focused implementation modules under `runtime/operator/`; expose their singleton controllers as MCP tools through VPS Ops, preserving `root_exec` as an independent recovery path. Desktop capture uses Pillow/X11 and input uses `xdotool`; secret typing sends bytes through `xdotool type --file -` stdin so secret values do not appear in argv.

**Tech Stack:** Python 3.12, FastMCP 1.28.0, Pillow `ImageGrab`, `xdotool`, stdlib `pty`/`selectors`/`subprocess`, systemd transient units/timers, pytest.

**Spec:** `docs/superpowers/specs/2026-09-03-eiros-full-vps-operator-design.md`

## Global Constraints

- Canonical checkout is `/opt/eiros-control-plane`; production services run from canonical `main`, never a transient worktree.
- Privileged MCP remains loopback/private; no public root, desktop, PTY, or secret endpoint is introduced.
- `Ebridge_VPS_Ops.root_exec` remains independently usable if desktop/operator helper code fails.
- noVNC remains an emergency human viewer, not the automation transport.
- Desktop scope is the entire `DISPLAY=:99`, not an application allowlist.
- Secret values must not be returned from tools, written to Git, placed in shell argv, or emitted to audit logs.
- New behavior is implemented TDD-first; every task runs focused tests before the broader operator suite.
- Critical network/control-plane changes use staged rollback and only cancel rollback after verification succeeds.

## File Structure

- Create `runtime/operator/__init__.py` — package exports and singleton-neutral types.
- Create `runtime/operator/audit.py` — JSONL redacted operator audit writer.
- Create `runtime/operator/files.py` — unrestricted root filesystem primitives with atomic writes.
- Create `runtime/operator/desktop.py` — frame capture, window discovery/focus, pointer/key/text/clipboard/wait operations, serialized mutation lock.
- Create `runtime/operator/secrets.py` — root-owned named secret store and non-argv injection helpers.
- Create `runtime/operator/pty.py` — persistent root PTY session manager with bounded sequenced reads.
- Create `runtime/operator/recovery.py` — rollback transaction manager and transient systemd rollback scheduling.
- Create `runtime/test_operator_files.py`, `runtime/test_operator_desktop.py`, `runtime/test_operator_secrets.py`, `runtime/test_operator_pty.py`, `runtime/test_operator_recovery.py`.
- Modify `runtime/vps_ops_server.py` — instantiate controllers and register model-facing MCP tools.
- Modify `runtime/test_claude_operator_mcp_server.py` — assert new VPS tools are mirrored into EIROS Operator.
- Modify `deploy/eiros-claude-operator.service` only if runtime environment needs explicit `DISPLAY=:99`; desktop tools themselves still accept/own the display value.

---

### Task 1: Unrestricted Filesystem Primitives and Redacted Audit

**Files:**
- Create: `runtime/operator/__init__.py`
- Create: `runtime/operator/audit.py`
- Create: `runtime/operator/files.py`
- Create: `runtime/test_operator_files.py`

**Interfaces:**
- Produces: `AuditLog(path: Path).write(tool: str, ok: bool, target: dict[str, object], duration_ms: int, rollback_id: str = "") -> None`
- Produces: `RootFiles` methods `stat`, `list`, `read`, `write_atomic`, `replace`, `copy`, `move`, `mkdir`, `delete`, `chmod`, `chown`.
- No path allowlist is applied by `RootFiles`.

- [ ] **Step 1: Write failing filesystem/audit tests**

```python
# runtime/test_operator_files.py
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
```

- [ ] **Step 2: Run tests and verify RED**

Run: `./venv/bin/pytest -q runtime/test_operator_files.py`
Expected: collection/import failure because `runtime.operator.audit` and `runtime.operator.files` do not exist.

- [ ] **Step 3: Implement minimal audit/files modules**

```python
# runtime/operator/audit.py
from __future__ import annotations
import json, os, time
from pathlib import Path

_DENY = {"password", "secret", "token", "api_key", "private_key", "value", "content"}

class AuditLog:
    def __init__(self, path: Path = Path("/var/log/eiros/operator-audit.jsonl")) -> None:
        self.path = Path(path)

    def write(self, tool: str, ok: bool, target: dict[str, object], duration_ms: int, rollback_id: str = "") -> None:
        safe = {k: v for k, v in target.items() if k.lower() not in _DENY}
        event = {"ts": time.time(), "tool": tool, "ok": bool(ok), "duration_ms": int(duration_ms), "target": safe, "rollback_id": rollback_id}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, (json.dumps(event, ensure_ascii=False) + "\n").encode())
        finally:
            os.close(fd)
```

```python
# runtime/operator/files.py
from __future__ import annotations
import os, shutil, stat, tempfile
from pathlib import Path

class RootFiles:
    def stat(self, path: str) -> dict[str, object]:
        p = Path(path).expanduser()
        s = p.lstat()
        return {"path": str(p), "size": s.st_size, "mode": format(stat.S_IMODE(s.st_mode), "04o"), "uid": s.st_uid, "gid": s.st_gid, "is_file": p.is_file(), "is_dir": p.is_dir(), "is_symlink": p.is_symlink()}

    def list(self, path: str) -> list[dict[str, object]]:
        p = Path(path).expanduser()
        return [self.stat(str(x)) for x in sorted(p.iterdir(), key=lambda x: x.name)]

    def read(self, path: str, max_bytes: int = 200000) -> dict[str, object]:
        p = Path(path).expanduser(); data = p.read_bytes(); limit = max(1, min(int(max_bytes), 2_000_000))
        return {"path": str(p), "content": data[:limit].decode("utf-8", "replace"), "size": len(data), "truncated": len(data) > limit}

    def write_atomic(self, path: str, content: str, mode: int = 0o600) -> dict[str, object]:
        p = Path(path).expanduser(); p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=f".{p.name}.", dir=str(p.parent))
        try:
            os.fchmod(fd, int(mode)); os.write(fd, content.encode()); os.fsync(fd); os.close(fd); fd = -1; os.replace(tmp, p)
        finally:
            if fd >= 0: os.close(fd)
            if os.path.exists(tmp): os.unlink(tmp)
        return self.stat(str(p))

    def replace(self, path: str, old: str, new: str, count: int = 1) -> dict[str, object]:
        p = Path(path).expanduser(); text = p.read_text(); updated = text.replace(old, new, count if count > 0 else -1)
        if updated == text: raise ValueError("old text not found")
        return self.write_atomic(str(p), updated, stat.S_IMODE(p.stat().st_mode))

    def copy(self, src: str, dst: str) -> dict[str, object]: shutil.copy2(src, dst); return self.stat(dst)
    def move(self, src: str, dst: str) -> dict[str, object]: shutil.move(src, dst); return self.stat(dst)
    def mkdir(self, path: str, mode: int = 0o755) -> dict[str, object]: Path(path).mkdir(parents=True, exist_ok=True, mode=mode); return self.stat(path)
    def delete(self, path: str, recursive: bool = False) -> dict[str, object]:
        p = Path(path); existed = p.exists() or p.is_symlink()
        if p.is_dir() and not p.is_symlink():
            if recursive: shutil.rmtree(p)
            else: p.rmdir()
        elif existed: p.unlink()
        return {"ok": True, "path": str(p), "existed": existed}
    def chmod(self, path: str, mode: int) -> dict[str, object]: os.chmod(path, mode); return self.stat(path)
    def chown(self, path: str, uid: int, gid: int) -> dict[str, object]: os.chown(path, uid, gid); return self.stat(path)
```

- [ ] **Step 4: Run focused tests GREEN**

Run: `./venv/bin/pytest -q runtime/test_operator_files.py`
Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add runtime/operator/__init__.py runtime/operator/audit.py runtime/operator/files.py runtime/test_operator_files.py && git commit -m "feat: add unrestricted operator filesystem primitives"`

---

### Task 2: Model-Visible Desktop Controller for DISPLAY=:99

**Files:**
- Create: `runtime/operator/desktop.py`
- Create: `runtime/test_operator_desktop.py`

**Interfaces:**
- Produces: `DesktopController(display=":99")` with `status`, `capture`, `windows`, `focus`, `pointer`, `drag`, `scroll`, `key`, `text`, `clipboard_set`, `wait`.
- `capture()` returns metadata plus raw JPEG bytes internally; MCP wrapping in Task 6 converts bytes to FastMCP `Image`.
- Mutations are serialized by a process-local lease lock.

- [ ] **Step 1: Write failing desktop tests using an injected backend**

```python
# runtime/test_operator_desktop.py
from runtime.operator.desktop import DesktopController

class FakeBackend:
    def __init__(self): self.frame = b"A"; self.events = []
    def capture_jpeg(self, region=None): return self.frame, (1440, 900)
    def windows(self): return [{"id": "11", "name": "Demo"}]
    def focus(self, window_id): self.events.append(("focus", window_id))
    def run_input(self, argv, stdin=None): self.events.append((tuple(argv), stdin))


def test_capture_sequence_changes_only_when_frame_changes() -> None:
    backend = FakeBackend(); ctl = DesktopController(backend=backend)
    a = ctl.capture(); b = ctl.capture(); backend.frame = b"B"; c = ctl.capture()
    assert (a["frame_seq"], b["frame_seq"], c["frame_seq"]) == (1, 1, 2)
    assert c["jpeg"] == b"B"


def test_text_uses_xdotool_file_stdin_not_argv() -> None:
    backend = FakeBackend(); ctl = DesktopController(backend=backend)
    ctl.text("hello world")
    argv, stdin = backend.events[-1]
    assert argv[-2:] == ("--file", "-")
    assert "hello world" not in " ".join(argv)
    assert stdin == b"hello world"
```

- [ ] **Step 2: Run tests RED**

Run: `./venv/bin/pytest -q runtime/test_operator_desktop.py`
Expected: import failure for `runtime.operator.desktop`.

- [ ] **Step 3: Implement X11 backend and controller**

```python
# runtime/operator/desktop.py
from __future__ import annotations
import hashlib, os, subprocess, threading, time
from io import BytesIO
from PIL import ImageGrab

class X11Backend:
    def __init__(self, display: str = ":99") -> None: self.display = display
    def _env(self): return {**os.environ, "DISPLAY": self.display}
    def capture_jpeg(self, region=None):
        image = ImageGrab.grab(bbox=tuple(region) if region else None, xdisplay=self.display)
        out = BytesIO(); image.convert("RGB").save(out, format="JPEG", quality=58, optimize=True)
        return out.getvalue(), image.size
    def windows(self):
        p = subprocess.run(["xdotool", "search", "--onlyvisible", "--name", ".*"], env=self._env(), text=True, capture_output=True, check=False)
        result = []
        for wid in [x for x in p.stdout.splitlines() if x.strip()]:
            name = subprocess.run(["xdotool", "getwindowname", wid], env=self._env(), text=True, capture_output=True).stdout.strip()
            result.append({"id": wid, "name": name})
        return result
    def focus(self, window_id): subprocess.run(["xdotool", "windowactivate", "--sync", str(window_id)], env=self._env(), check=True)
    def run_input(self, argv, stdin=None): subprocess.run(list(argv), env=self._env(), input=stdin, check=True)

class DesktopController:
    def __init__(self, display: str = ":99", backend=None) -> None:
        self.display = display; self.backend = backend or X11Backend(display); self._lock = threading.RLock(); self._hash = ""; self._seq = 0
    def status(self):
        frame = self.capture(); return {k: v for k, v in frame.items() if k != "jpeg"} | {"display": self.display, "backend": type(self.backend).__name__}
    def capture(self, region=None):
        jpeg, size = self.backend.capture_jpeg(region); digest = hashlib.sha256(jpeg).hexdigest()
        if digest != self._hash: self._hash = digest; self._seq += 1
        return {"frame_seq": self._seq, "sha256": digest, "width": size[0], "height": size[1], "jpeg": jpeg}
    def windows(self): return self.backend.windows()
    def focus(self, window_id):
        with self._lock: self.backend.focus(window_id)
    def pointer(self, x, y, button=1, clicks=1):
        with self._lock: self.backend.run_input(["xdotool", "mousemove", "--sync", str(int(x)), str(int(y)), "click", "--repeat", str(int(clicks)), str(int(button))])
    def drag(self, x1, y1, x2, y2, button=1):
        with self._lock: self.backend.run_input(["xdotool", "mousemove", str(int(x1)), str(int(y1)), "mousedown", str(button), "mousemove", "--sync", str(int(x2)), str(int(y2)), "mouseup", str(button)])
    def scroll(self, amount):
        button = "4" if int(amount) < 0 else "5"
        with self._lock: self.backend.run_input(["xdotool", "click", "--repeat", str(abs(int(amount))), button])
    def key(self, key):
        with self._lock: self.backend.run_input(["xdotool", "key", "--clearmodifiers", str(key)])
    def text(self, text):
        with self._lock: self.backend.run_input(["xdotool", "type", "--clearmodifiers", "--delay", "1", "--file", "-"], stdin=str(text).encode())
    def clipboard_set(self, text):
        with self._lock: subprocess.run(["xclip", "-selection", "clipboard"], env={**os.environ, "DISPLAY": self.display}, input=str(text).encode(), check=True)
    def wait(self, after_seq, timeout_seconds=10.0):
        deadline = time.monotonic() + float(timeout_seconds)
        while time.monotonic() < deadline:
            frame = self.capture()
            if frame["frame_seq"] > int(after_seq): return {k: v for k, v in frame.items() if k != "jpeg"}
            time.sleep(0.2)
        return {"changed": False, "frame_seq": self._seq}
```

- [ ] **Step 4: Install clipboard dependency and run tests**

Run: `apt-get update -qq && apt-get install -y xclip && ./venv/bin/pytest -q runtime/test_operator_desktop.py`
Expected: PASS.

- [ ] **Step 5: Run real frame/input smoke probe on :99 without changing MT5 state**

Run: `DISPLAY=:99 ./venv/bin/python -c 'from runtime.operator.desktop import DesktopController; c=DesktopController(); f=c.capture(); print(f["width"],f["height"],len(f["jpeg"]),len(c.windows()))'`
Expected: `1440 900`, non-zero JPEG byte count, non-zero visible-window count.

- [ ] **Step 6: Commit**

Run: `git add runtime/operator/desktop.py runtime/test_operator_desktop.py && git commit -m "feat: add full display operator controller"`

---

### Task 3: Local Secret Broker and Non-argv Secret Injection

**Files:**
- Create: `runtime/operator/secrets.py`
- Create: `runtime/test_operator_secrets.py`

**Interfaces:**
- Produces: `SecretStore(root=Path("/var/lib/eiros-operator/secrets"))` with `set`, `exists`, `list`, `delete`, `type_into_desktop`, `run_with_env`, `run_with_stdin`.
- Secret values never appear in return dictionaries.

- [ ] **Step 1: Write failing secret tests**

```python
# runtime/test_operator_secrets.py
from pathlib import Path
from runtime.operator.secrets import SecretStore

class FakeDesktop:
    def __init__(self): self.payload = None
    def type_bytes(self, payload): self.payload = payload


def test_store_permissions_and_redacted_metadata(tmp_path: Path) -> None:
    store = SecretStore(tmp_path / "secrets")
    result = store.set("broker_password", "s3cr3t")
    assert result == {"ok": True, "name": "broker_password", "bytes": 6}
    assert (tmp_path / "secrets" / "broker_password").stat().st_mode & 0o777 == 0o600
    assert "s3cr3t" not in repr(store.list())


def test_type_secret_by_effect_without_returning_value(tmp_path: Path) -> None:
    store = SecretStore(tmp_path / "secrets"); store.set("broker_password", "s3cr3t")
    desktop = FakeDesktop(); result = store.type_into_desktop("broker_password", desktop)
    assert desktop.payload == b"s3cr3t"
    assert result == {"ok": True, "name": "broker_password", "bytes": 6}
    assert "s3cr3t" not in repr(result)


def test_process_output_is_redacted_even_if_child_echoes_secret(tmp_path: Path) -> None:
    store = SecretStore(tmp_path / "secrets"); store.set("broker_password", "s3cr3t")
    result = store.run_with_env({"BROKER_PASS": "broker_password"}, ["/bin/sh", "-c", "printf %s \"$BROKER_PASS\""])
    assert result["ok"] is True
    assert "s3cr3t" not in repr(result)
    assert result["stdout"] == "***REDACTED***"
```

- [ ] **Step 2: Run tests RED**

Run: `./venv/bin/pytest -q runtime/test_operator_secrets.py`
Expected: import failure for `runtime.operator.secrets`.

- [ ] **Step 3: Add `DesktopController.type_bytes` and implement SecretStore**

```python
# add to DesktopController in runtime/operator/desktop.py
def type_bytes(self, payload: bytes) -> None:
    with self._lock:
        self.backend.run_input(["xdotool", "type", "--clearmodifiers", "--delay", "1", "--file", "-"], stdin=bytes(payload))
```

```python
# runtime/operator/secrets.py
from __future__ import annotations
import os, re, subprocess
from pathlib import Path

_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")

class SecretStore:
    def __init__(self, root: Path = Path("/var/lib/eiros-operator/secrets")) -> None:
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True); os.chmod(self.root, 0o700)
    def _path(self, name: str) -> Path:
        if not _NAME.fullmatch(name): raise ValueError("invalid secret name")
        return self.root / name
    def set(self, name: str, value: str):
        p = self._path(name); data = value.encode(); fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try: os.write(fd, data); os.fsync(fd)
        finally: os.close(fd)
        os.chmod(p, 0o600); return {"ok": True, "name": name, "bytes": len(data)}
    def exists(self, name: str): return {"ok": True, "name": name, "exists": self._path(name).is_file()}
    def list(self): return [{"name": p.name, "bytes": p.stat().st_size, "mode": "0600"} for p in sorted(self.root.iterdir()) if p.is_file()]
    def delete(self, name: str): p=self._path(name); existed=p.exists(); p.unlink(missing_ok=True); return {"ok": True, "name": name, "existed": existed}
    def _read(self, name: str) -> bytes: return self._path(name).read_bytes()
    @staticmethod
    def _redact(data: bytes, secrets: list[bytes]) -> str:
        for secret in secrets:
            if secret: data = data.replace(secret, b"***REDACTED***")
        return data.decode("utf-8", "replace")[-200000:]
    def type_into_desktop(self, name: str, desktop):
        data=self._read(name); desktop.type_bytes(data); return {"ok": True, "name": name, "bytes": len(data)}
    def run_with_stdin(self, name: str, argv: list[str], cwd: str = "/"):
        data=self._read(name); p=subprocess.run(argv, cwd=cwd, input=data, capture_output=True)
        return {"ok": p.returncode==0, "exit_code": p.returncode, "stdout": self._redact(p.stdout,[data]), "stderr": self._redact(p.stderr,[data])}
    def run_with_env(self, mapping: dict[str,str], argv: list[str], cwd: str = "/"):
        env=os.environ.copy(); values=[]
        for env_name, secret_name in mapping.items():
            value=self._read(secret_name); values.append(value); env[env_name]=value.decode()
        p=subprocess.run(argv, cwd=cwd, env=env, capture_output=True)
        return {"ok": p.returncode==0, "exit_code": p.returncode, "stdout": self._redact(p.stdout,values), "stderr": self._redact(p.stderr,values)}
```

- [ ] **Step 4: Run focused desktop+secret tests GREEN**

Run: `./venv/bin/pytest -q runtime/test_operator_desktop.py runtime/test_operator_secrets.py`
Expected: PASS and no secret value in pytest output.

- [ ] **Step 5: Commit**

Run: `git add runtime/operator/desktop.py runtime/operator/secrets.py runtime/test_operator_desktop.py runtime/test_operator_secrets.py && git commit -m "feat: add local operator secret broker"`

---

### Task 4: Persistent Root PTY Manager

**Files:**
- Create: `runtime/operator/pty.py`
- Create: `runtime/test_operator_pty.py`

**Interfaces:**
- Produces: `PtyManager` with `start`, `write`, `read`, `resize`, `signal`, `close`, `list`.
- Output is sequence-numbered and bounded; a read timeout never destroys the session.

- [ ] **Step 1: Write failing PTY lifecycle test**

```python
# runtime/test_operator_pty.py
import time
from runtime.operator.pty import PtyManager


def test_persistent_shell_write_read_and_close() -> None:
    mgr = PtyManager(max_buffer=65536)
    s = mgr.start("/bin/bash", cwd="/")
    mgr.write(s["session_id"], "printf 'PTY_OK\\n'\n")
    deadline=time.time()+3; out=""; seq=0
    while time.time()<deadline and "PTY_OK" not in out:
        r=mgr.read(s["session_id"], after_seq=seq); seq=r["seq"]; out += r["data"]; time.sleep(0.05)
    assert "PTY_OK" in out
    assert mgr.close(s["session_id"])["closed"] is True
```

- [ ] **Step 2: Run test RED**

Run: `./venv/bin/pytest -q runtime/test_operator_pty.py`
Expected: import failure for `runtime.operator.pty`.

- [ ] **Step 3: Implement PTY manager with stdlib `pty`**

```python
# runtime/operator/pty.py
from __future__ import annotations
import errno, fcntl, os, pty, signal, struct, subprocess, termios, threading, uuid
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
    lock: threading.RLock = field(default_factory=threading.RLock)

class PtyManager:
    def __init__(self, max_buffer: int = 1_000_000) -> None:
        self.max_buffer = int(max_buffer); self._sessions: dict[str, _Session] = {}; self._lock = threading.RLock()

    def start(self, command: str = "/bin/bash", cwd: str = "/") -> dict[str, object]:
        master, slave = pty.openpty()
        proc = subprocess.Popen(command, shell=True, executable="/bin/bash", cwd=cwd, stdin=slave, stdout=slave, stderr=slave, start_new_session=True, close_fds=True)
        os.close(slave); sid=f"pty_{uuid.uuid4().hex}"; session=_Session(sid, master, proc)
        with self._lock: self._sessions[sid]=session
        threading.Thread(target=self._reader, args=(session,), daemon=True, name=sid).start()
        return {"session_id": sid, "pid": proc.pid, "running": True, "cwd": cwd, "command": command}

    def _reader(self, session: _Session) -> None:
        while True:
            try: data=os.read(session.master_fd, 8192)
            except OSError as exc:
                if exc.errno in {errno.EIO, errno.EBADF}: break
                raise
            if not data: break
            with session.lock:
                session.seq += 1; session.chunks.append((session.seq, data)); session.buffered += len(data)
                while session.buffered > self.max_buffer and session.chunks:
                    _, dropped=session.chunks.popleft(); session.buffered -= len(dropped)

    def _get(self, session_id: str) -> _Session:
        with self._lock:
            if session_id not in self._sessions: raise KeyError(f"PTY session not found: {session_id}")
            return self._sessions[session_id]

    def write(self, session_id: str, data: str) -> dict[str, object]:
        s=self._get(session_id); payload=data.encode(); os.write(s.master_fd, payload); return {"session_id": session_id, "bytes": len(payload)}

    def read(self, session_id: str, after_seq: int = 0, max_chars: int = 200000) -> dict[str, object]:
        s=self._get(session_id)
        with s.lock:
            oldest=s.chunks[0][0] if s.chunks else s.seq + 1
            payload=b"".join(data for seq,data in s.chunks if seq > int(after_seq))
            truncated=int(after_seq) < oldest-1 or len(payload) > int(max_chars)
            payload=payload[-max(1,min(int(max_chars),200000)):]
            code=s.proc.poll()
            return {"session_id": session_id, "seq": s.seq, "data": payload.decode("utf-8","replace"), "running": code is None, "exit_code": code, "truncated": truncated}

    def resize(self, session_id: str, rows: int, cols: int) -> dict[str, object]:
        s=self._get(session_id); fcntl.ioctl(s.master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", int(rows), int(cols), 0, 0)); return {"session_id": session_id, "rows": int(rows), "cols": int(cols)}

    def signal(self, session_id: str, sig: int) -> dict[str, object]:
        s=self._get(session_id); os.killpg(os.getpgid(s.proc.pid), int(sig)); return {"session_id": session_id, "signal": int(sig)}

    def close(self, session_id: str) -> dict[str, object]:
        s=self._get(session_id)
        if s.proc.poll() is None:
            try: os.killpg(os.getpgid(s.proc.pid), signal.SIGTERM); s.proc.wait(timeout=2)
            except Exception:
                try: os.killpg(os.getpgid(s.proc.pid), signal.SIGKILL)
                except ProcessLookupError: pass
        try: os.close(s.master_fd)
        except OSError: pass
        with self._lock: self._sessions.pop(session_id, None)
        return {"session_id": session_id, "closed": True, "exit_code": s.proc.poll()}

    def list(self) -> list[dict[str, object]]:
        with self._lock:
            return [{"session_id": s.session_id, "pid": s.proc.pid, "running": s.proc.poll() is None, "seq": s.seq} for s in self._sessions.values()]
```

- [ ] **Step 4: Run focused PTY test GREEN**

Run: `./venv/bin/pytest -q runtime/test_operator_pty.py`
Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add runtime/operator/pty.py runtime/test_operator_pty.py && git commit -m "feat: add persistent root PTY manager"`

---

### Task 5: Rollback-Protected Critical Configuration Transactions

**Files:**
- Create: `runtime/operator/recovery.py`
- Create: `runtime/test_operator_recovery.py`
- Create: `deploy/eiros_operator_rollback.py`

**Interfaces:**
- Produces: `RecoveryManager(root=Path("/var/lib/eiros-operator/rollback"))` with `stage(paths, seconds)`, `atomic_write(tx_id, path, content, mode)`, `verify(tx_id, argv)`, `commit(tx_id)`, `rollback(tx_id)`, `status(tx_id)`.
- A staged transaction schedules a transient `systemd-run` timer; commit cancels it.

- [ ] **Step 1: Write failing rollback test using injected scheduler**

```python
# runtime/test_operator_recovery.py
from pathlib import Path
from runtime.operator.recovery import RecoveryManager

class FakeScheduler:
    def __init__(self): self.scheduled=[]; self.cancelled=[]
    def schedule(self, tx_id, seconds): self.scheduled.append((tx_id, seconds))
    def cancel(self, tx_id): self.cancelled.append(tx_id)


def test_failed_verify_restores_original_file(tmp_path: Path) -> None:
    target=tmp_path/"config"; target.write_text("good")
    sched=FakeScheduler(); mgr=RecoveryManager(tmp_path/"rb", scheduler=sched)
    tx=mgr.stage([str(target)], seconds=30)["tx_id"]
    mgr.atomic_write(tx, str(target), "bad", 0o600)
    result=mgr.verify(tx, ["/bin/false"])
    assert result["ok"] is False
    assert target.read_text()=="good"
    assert mgr.status(tx)["state"]=="rolled_back"
```

- [ ] **Step 2: Run test RED**

Run: `./venv/bin/pytest -q runtime/test_operator_recovery.py`
Expected: import failure for `runtime.operator.recovery`.

- [ ] **Step 3: Implement transaction manager and rollback entrypoint**

```python
# runtime/operator/recovery.py
from __future__ import annotations
import json, os, shutil, stat, subprocess, tempfile, uuid
from pathlib import Path

class SystemdScheduler:
    def schedule(self, tx_id: str, seconds: int) -> None:
        subprocess.run([
            "systemd-run", f"--unit=eiros-operator-rollback-{tx_id}", f"--on-active={int(seconds)}s",
            "/opt/eiros-control-plane/venv/bin/python", "/opt/eiros-control-plane/deploy/eiros_operator_rollback.py", tx_id,
        ], check=True, capture_output=True)
    def cancel(self, tx_id: str) -> None:
        subprocess.run(["systemctl", "stop", f"eiros-operator-rollback-{tx_id}.timer"], check=False, capture_output=True)

class RecoveryManager:
    def __init__(self, root: Path = Path("/var/lib/eiros-operator/rollback"), scheduler=None) -> None:
        self.root=Path(root); self.root.mkdir(parents=True, exist_ok=True); os.chmod(self.root,0o700); self.scheduler=scheduler or SystemdScheduler()
    def _dir(self, tx_id: str) -> Path: return self.root / tx_id
    def _manifest_path(self, tx_id: str) -> Path: return self._dir(tx_id) / "manifest.json"
    def _load(self, tx_id: str) -> dict: return json.loads(self._manifest_path(tx_id).read_text())
    def _save(self, tx_id: str, manifest: dict) -> None:
        p=self._manifest_path(tx_id); tmp=p.with_suffix(".tmp"); tmp.write_text(json.dumps(manifest, indent=2)); os.chmod(tmp,0o600); os.replace(tmp,p)

    def stage(self, paths: list[str], seconds: int = 120) -> dict[str, object]:
        tx_id=f"rb_{uuid.uuid4().hex}"; d=self._dir(tx_id); (d/"backups").mkdir(parents=True); os.chmod(d,0o700)
        entries=[]
        for index, raw in enumerate(paths):
            p=Path(raw); existed=p.exists(); entry={"path":str(p),"existed":existed,"backup":"","mode":None,"uid":None,"gid":None}
            if existed:
                s=p.stat(); entry.update(mode=stat.S_IMODE(s.st_mode),uid=s.st_uid,gid=s.st_gid)
                backup=d/"backups"/f"{index}.bin"; shutil.copy2(p,backup); entry["backup"]=str(backup)
            entries.append(entry)
        manifest={"tx_id":tx_id,"state":"staged","seconds":int(seconds),"entries":entries}
        self._save(tx_id,manifest); self.scheduler.schedule(tx_id,int(seconds)); return {"ok":True,"tx_id":tx_id,"state":"staged","paths":[e["path"] for e in entries],"rollback_seconds":int(seconds)}

    def atomic_write(self, tx_id: str, path: str, content: str, mode: int = 0o600) -> dict[str, object]:
        m=self._load(tx_id)
        if m["state"] != "staged": raise ValueError(f"transaction not staged: {m['state']}")
        if path not in {e["path"] for e in m["entries"]}: raise ValueError("path was not staged")
        p=Path(path); p.parent.mkdir(parents=True,exist_ok=True); fd,tmp=tempfile.mkstemp(prefix=f".{p.name}.",dir=str(p.parent))
        try:
            os.fchmod(fd,int(mode)); os.write(fd,content.encode()); os.fsync(fd); os.close(fd); fd=-1; os.replace(tmp,p)
        finally:
            if fd>=0: os.close(fd)
            if os.path.exists(tmp): os.unlink(tmp)
        return {"ok":True,"tx_id":tx_id,"path":path,"bytes":len(content.encode())}

    def verify(self, tx_id: str, argv: list[str]) -> dict[str, object]:
        p=subprocess.run(argv,capture_output=True,text=True)
        if p.returncode != 0:
            rb=self.rollback(tx_id)
            return {"ok":False,"tx_id":tx_id,"exit_code":p.returncode,"stdout":p.stdout[-120000:],"stderr":p.stderr[-120000:],"rollback":rb}
        return {"ok":True,"tx_id":tx_id,"exit_code":0,"stdout":p.stdout[-120000:],"stderr":p.stderr[-120000:]}

    def commit(self, tx_id: str) -> dict[str, object]:
        m=self._load(tx_id); m["state"]="committed"; self._save(tx_id,m); self.scheduler.cancel(tx_id); return {"ok":True,"tx_id":tx_id,"state":"committed"}

    def rollback(self, tx_id: str) -> dict[str, object]:
        m=self._load(tx_id)
        if m["state"] == "rolled_back": return {"ok":True,"tx_id":tx_id,"state":"rolled_back","already":True}
        if m["state"] == "committed": raise ValueError("committed transaction cannot be rolled back automatically")
        for e in m["entries"]:
            p=Path(e["path"])
            if e["existed"]:
                p.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(e["backup"],p); os.chmod(p,int(e["mode"])); os.chown(p,int(e["uid"]),int(e["gid"]))
            elif p.exists() or p.is_symlink():
                if p.is_dir() and not p.is_symlink(): shutil.rmtree(p)
                else: p.unlink()
        m["state"]="rolled_back"; self._save(tx_id,m); self.scheduler.cancel(tx_id); return {"ok":True,"tx_id":tx_id,"state":"rolled_back"}

    def status(self, tx_id: str) -> dict[str, object]:
        m=self._load(tx_id); return {"ok":True,"tx_id":tx_id,"state":m["state"],"paths":[e["path"] for e in m["entries"]],"rollback_seconds":m["seconds"]}
```

```python
# deploy/eiros_operator_rollback.py
from __future__ import annotations
import sys
from runtime.operator.recovery import RecoveryManager

if __name__ == "__main__":
    if len(sys.argv) != 2: raise SystemExit("usage: eiros_operator_rollback.py <tx_id>")
    result=RecoveryManager().rollback(sys.argv[1])
    raise SystemExit(0 if result.get("ok") else 1)
```

- [ ] **Step 4: Run focused recovery tests GREEN**

Run: `./venv/bin/pytest -q runtime/test_operator_recovery.py`
Expected: PASS.

- [ ] **Step 5: Run reversible live timer smoke test**

Run:

```bash
./venv/bin/python - <<'PY'
import time
from pathlib import Path
from runtime.operator.recovery import RecoveryManager
p=Path('/tmp/eiros-rollback-smoke'); p.write_text('original')
m=RecoveryManager(); tx=m.stage([str(p)],seconds=8)['tx_id']; m.atomic_write(tx,str(p),'changed',0o600)
print(tx,p.read_text()); time.sleep(10); print(p.read_text(),m.status(tx))
assert p.read_text()=='original'
assert m.status(tx)['state']=='rolled_back'
PY
```

Expected: first print contains `changed`; after 10 seconds content is `original` and state is `rolled_back`.

- [ ] **Step 6: Commit**

Run: `git add runtime/operator/recovery.py runtime/test_operator_recovery.py deploy/eiros_operator_rollback.py && git commit -m "feat: add rollback protected operator transactions"`

---

### Task 6: Expose Full Operator MCP Surface and Deploy Safely

**Files:**
- Modify: `runtime/vps_ops_server.py`
- Modify: `runtime/test_claude_operator_mcp_server.py`
- Create: `runtime/test_full_operator_tools.py`
- Modify: `deploy/eiros-claude-operator.service` if needed for display defaults.

**Interfaces:**
- MCP tools added: `fs_stat`, `fs_list`, `fs_read`, `fs_write`, `fs_replace`, `fs_copy`, `fs_move`, `fs_mkdir`, `fs_delete`, `fs_chmod`, `fs_chown`.
- MCP tools added: `desktop_status`, `desktop_frame`, `desktop_windows`, `desktop_focus`, `desktop_pointer`, `desktop_drag`, `desktop_scroll`, `desktop_key`, `desktop_text`, `desktop_clipboard_set`, `desktop_wait`.
- MCP tools added: `secret_list`, `secret_exists`, `secret_set`, `secret_delete`, `secret_type`, `secret_exec_env`, `secret_exec_stdin`.
- MCP tools added: `pty_start`, `pty_write`, `pty_read`, `pty_resize`, `pty_signal`, `pty_close`, `pty_list`.
- MCP tools added: `critical_stage`, `critical_write`, `critical_verify`, `critical_commit`, `critical_rollback`, `critical_status`.

- [ ] **Step 1: Write failing tool-registration/mirroring test**

```python
# runtime/test_full_operator_tools.py
import asyncio
from runtime import vps_ops_server

REQUIRED={"fs_read","fs_write","desktop_status","desktop_frame","desktop_pointer","desktop_text","secret_list","secret_type","pty_start","pty_write","pty_read","critical_stage","critical_verify","critical_commit"}

def test_vps_ops_registers_full_operator_tools():
    names={t.name for t in asyncio.run(vps_ops_server.mcp.list_tools())}
    assert REQUIRED <= names
```

Add to `runtime/test_claude_operator_mcp_server.py`:

```python
def test_operator_mirrors_full_vps_operator_surface() -> None:
    import runtime.claude_operator_mcp_server as operator
    names = _tool_names(operator.mcp)
    assert {"desktop_frame", "secret_type", "pty_start", "fs_write", "critical_stage"} <= names
```

- [ ] **Step 2: Run registration tests RED**

Run: `./venv/bin/pytest -q runtime/test_full_operator_tools.py runtime/test_claude_operator_mcp_server.py`
Expected: FAIL because tools are not registered.

- [ ] **Step 3: Wire singleton controllers and MCP wrappers**

Add imports and controller singletons near the existing `FastMCP` setup:

```python
from mcp.server.fastmcp.utilities.types import Image
from runtime.operator.audit import AuditLog
from runtime.operator.desktop import DesktopController
from runtime.operator.files import RootFiles
from runtime.operator.pty import PtyManager
from runtime.operator.recovery import RecoveryManager
from runtime.operator.secrets import SecretStore

AUDIT = AuditLog()
ROOT_FILES = RootFiles()
DESKTOP = DesktopController(os.getenv("EIROS_OPERATOR_DISPLAY", ":99"))
SECRETS = SecretStore()
PTY = PtyManager()
RECOVERY = RecoveryManager()


def _audit_call(tool: str, target: dict[str, object], fn):
    started=time.time()
    try:
        result=fn(); AUDIT.write(tool,True,target,int((time.time()-started)*1000)); return result
    except Exception:
        AUDIT.write(tool,False,target,int((time.time()-started)*1000)); raise


def _desktop_mutation(tool: str, target: dict[str, object], fn):
    before=DESKTOP.capture(); _audit_call(tool,target,fn); after=DESKTOP.capture()
    return {"ok":True,"before_seq":before["frame_seq"],"after_seq":after["frame_seq"],"frame_changed":after["frame_seq"]>before["frame_seq"]}
```

Register the unrestricted filesystem tools:

```python
@mcp.tool()
def fs_stat(path: str): return ROOT_FILES.stat(path)
@mcp.tool()
def fs_list(path: str): return ROOT_FILES.list(path)
@mcp.tool()
def fs_read(path: str, max_bytes: int = 200000): return ROOT_FILES.read(path,max_bytes)
@mcp.tool()
def fs_write(path: str, content: str, mode: int = 0o600): return _audit_call("fs_write",{"path":path},lambda:ROOT_FILES.write_atomic(path,content,mode))
@mcp.tool()
def fs_replace(path: str, old: str, new: str, count: int = 1): return _audit_call("fs_replace",{"path":path},lambda:ROOT_FILES.replace(path,old,new,count))
@mcp.tool()
def fs_copy(src: str, dst: str): return _audit_call("fs_copy",{"src":src,"dst":dst},lambda:ROOT_FILES.copy(src,dst))
@mcp.tool()
def fs_move(src: str, dst: str): return _audit_call("fs_move",{"src":src,"dst":dst},lambda:ROOT_FILES.move(src,dst))
@mcp.tool()
def fs_mkdir(path: str, mode: int = 0o755): return _audit_call("fs_mkdir",{"path":path},lambda:ROOT_FILES.mkdir(path,mode))
@mcp.tool()
def fs_delete(path: str, recursive: bool = False): return _audit_call("fs_delete",{"path":path,"recursive":recursive},lambda:ROOT_FILES.delete(path,recursive))
@mcp.tool()
def fs_chmod(path: str, mode: int): return _audit_call("fs_chmod",{"path":path,"mode":oct(mode)},lambda:ROOT_FILES.chmod(path,mode))
@mcp.tool()
def fs_chown(path: str, uid: int, gid: int): return _audit_call("fs_chown",{"path":path,"uid":uid,"gid":gid},lambda:ROOT_FILES.chown(path,uid,gid))
```

Register desktop tools with native MCP image content:

```python
@mcp.tool()
def desktop_status(): return DESKTOP.status()
@mcp.tool()
def desktop_frame(after_seq: int = 0, region: list[int] | None = None) -> list[Any]:
    frame=DESKTOP.capture(region); meta={k:v for k,v in frame.items() if k!="jpeg"}
    if frame["frame_seq"] <= int(after_seq): return [meta | {"frame_changed":False}]
    return [meta | {"frame_changed":True}, Image(data=frame["jpeg"],format="jpeg")]
@mcp.tool()
def desktop_windows(): return DESKTOP.windows()
@mcp.tool()
def desktop_focus(window_id: str): return _desktop_mutation("desktop_focus",{"window_id":window_id},lambda:DESKTOP.focus(window_id))
@mcp.tool()
def desktop_pointer(x: int, y: int, button: int = 1, clicks: int = 1): return _desktop_mutation("desktop_pointer",{"x":x,"y":y,"button":button,"clicks":clicks},lambda:DESKTOP.pointer(x,y,button,clicks))
@mcp.tool()
def desktop_drag(x1: int, y1: int, x2: int, y2: int, button: int = 1): return _desktop_mutation("desktop_drag",{"x1":x1,"y1":y1,"x2":x2,"y2":y2,"button":button},lambda:DESKTOP.drag(x1,y1,x2,y2,button))
@mcp.tool()
def desktop_scroll(amount: int): return _desktop_mutation("desktop_scroll",{"amount":amount},lambda:DESKTOP.scroll(amount))
@mcp.tool()
def desktop_key(key: str): return _desktop_mutation("desktop_key",{"key":key},lambda:DESKTOP.key(key))
@mcp.tool()
def desktop_text(text: str): return _desktop_mutation("desktop_text",{"chars":len(text)},lambda:DESKTOP.text(text))
@mcp.tool()
def desktop_clipboard_set(text: str): return _audit_call("desktop_clipboard_set",{"chars":len(text)},lambda:DESKTOP.clipboard_set(text))
@mcp.tool()
def desktop_wait(after_seq: int, timeout_seconds: float = 10.0): return DESKTOP.wait(after_seq,timeout_seconds)
```

Register secret tools without returning values:

```python
@mcp.tool()
def secret_list(): return SECRETS.list()
@mcp.tool()
def secret_exists(name: str): return SECRETS.exists(name)
@mcp.tool()
def secret_set(name: str, value: str): return _audit_call("secret_set",{"secret_name":name},lambda:SECRETS.set(name,value))
@mcp.tool()
def secret_delete(name: str): return _audit_call("secret_delete",{"secret_name":name},lambda:SECRETS.delete(name))
@mcp.tool()
def secret_type(name: str): return _desktop_mutation("secret_type",{"secret_name":name},lambda:SECRETS.type_into_desktop(name,DESKTOP))
@mcp.tool()
def secret_exec_env(mapping: dict[str,str], argv: list[str], cwd: str = "/"): return _audit_call("secret_exec_env",{"secret_names":sorted(mapping.values()),"argv0":argv[0] if argv else ""},lambda:SECRETS.run_with_env(mapping,argv,cwd))
@mcp.tool()
def secret_exec_stdin(name: str, argv: list[str], cwd: str = "/"): return _audit_call("secret_exec_stdin",{"secret_name":name,"argv0":argv[0] if argv else ""},lambda:SECRETS.run_with_stdin(name,argv,cwd))
```

Register PTY and recovery tools:

```python
@mcp.tool()
def pty_start(command: str = "/bin/bash", cwd: str = "/"): return _audit_call("pty_start",{"cwd":cwd,"command_chars":len(command)},lambda:PTY.start(command,cwd))
@mcp.tool()
def pty_write(session_id: str, data: str): return PTY.write(session_id,data)
@mcp.tool()
def pty_read(session_id: str, after_seq: int = 0, max_chars: int = 200000): return PTY.read(session_id,after_seq,max_chars)
@mcp.tool()
def pty_resize(session_id: str, rows: int, cols: int): return PTY.resize(session_id,rows,cols)
@mcp.tool()
def pty_signal(session_id: str, sig: int): return PTY.signal(session_id,sig)
@mcp.tool()
def pty_close(session_id: str): return PTY.close(session_id)
@mcp.tool()
def pty_list(): return PTY.list()
@mcp.tool()
def critical_stage(paths: list[str], seconds: int = 120): return _audit_call("critical_stage",{"paths":paths,"seconds":seconds},lambda:RECOVERY.stage(paths,seconds))
@mcp.tool()
def critical_write(tx_id: str, path: str, content: str, mode: int = 0o600): return _audit_call("critical_write",{"tx_id":tx_id,"path":path},lambda:RECOVERY.atomic_write(tx_id,path,content,mode))
@mcp.tool()
def critical_verify(tx_id: str, argv: list[str]): return _audit_call("critical_verify",{"tx_id":tx_id,"argv0":argv[0] if argv else ""},lambda:RECOVERY.verify(tx_id,argv))
@mcp.tool()
def critical_commit(tx_id: str): return _audit_call("critical_commit",{"tx_id":tx_id},lambda:RECOVERY.commit(tx_id))
@mcp.tool()
def critical_rollback(tx_id: str): return _audit_call("critical_rollback",{"tx_id":tx_id},lambda:RECOVERY.rollback(tx_id))
@mcp.tool()
def critical_status(tx_id: str): return RECOVERY.status(tx_id)
```

- [ ] **Step 4: Run focused and operator tests GREEN**

Run: `./venv/bin/pytest -q runtime/test_operator_files.py runtime/test_operator_desktop.py runtime/test_operator_secrets.py runtime/test_operator_pty.py runtime/test_operator_recovery.py runtime/test_full_operator_tools.py runtime/test_claude_operator_mcp_server.py`
Expected: PASS.

- [ ] **Step 5: Compile and run operator tool-list probe before restart**

Run: `./venv/bin/python -m py_compile runtime/operator/*.py runtime/vps_ops_server.py deploy/claude_operator_runtime.py && ./venv/bin/python deploy/claude_operator_runtime.py --list-tools | grep -E 'desktop_frame|secret_type|pty_start|fs_write|critical_stage'`
Expected: all five names present.

- [ ] **Step 6: Deploy with independent rollback/recovery channel intact**

Copy the current systemd unit to `/var/lib/eiros-operator/deploy-backups/eiros-claude-operator.service.<timestamp>`, run `systemctl daemon-reload`, restart only `eiros-claude-operator.service`, and verify `systemctl is-active eiros-claude-operator.service` plus a local MCP/tool-list health probe. Do not restart `eiros-vps-ops-http.service` or the independent root path unless its own code changed and verification requires it.

- [ ] **Step 7: Commit**

Run: `git add runtime/vps_ops_server.py runtime/test_full_operator_tools.py runtime/test_claude_operator_mcp_server.py deploy/eiros-claude-operator.service && git commit -m "feat: expose full EIROS VPS operator surface"`

---

### Task 7: IC Markets End-to-End Acceptance and Recorder Recovery

**Files:**
- No production code unless acceptance exposes a defect; defects get a failing regression test before repair.
- Operational state: `/var/lib/eiros-operator/secrets/`, IC Markets MT5 Wine profile, MT5 MCP/recorder systemd units.

**Interfaces:**
- Consumes MCP tools from Task 6 and existing MT5 services.
- Produces verified broker/session/feed state without Rico using noVNC.

- [ ] **Step 1: Verify operator can see and control the desktop entirely through MCP**

Call `desktop_status`, `desktop_frame`, `desktop_windows`; focus the IC Markets MT5 window and obtain a fresh model-visible frame. Use `desktop_pointer`/`desktop_key` to open the login flow. After every consequential action call `desktop_frame(after_seq=<previous>)` or `desktop_wait` and verify the expected visual/window change.

- [ ] **Step 2: Populate named broker secret through the dedicated secret tool**

Create `icmarkets_demo_password` with `secret_set`; verify only `secret_exists`/metadata are returned. Never echo the value after storage.

- [ ] **Step 3: Complete IC Markets login without noVNC input**

Use ordinary `desktop_text` for non-secret login/server values, `secret_type("icmarkets_demo_password")` for the password, submit the dialog, and inspect the new frame/state. If focus is ambiguous, reacquire the window/frame before another input instead of repeating blindly.

- [ ] **Step 4: Verify broker/feed state through independent evidence**

Use the IC Markets MT5 Python SDK path to verify `account_info()` is non-null, server/company match IC Markets/Raw Trading Ltd, `trade_mode` is demo, GBPUSD tick time is current, and `symbol_info_tick("GBPUSD")` returns bid/ask. Confirm DOM availability with `market_book_add`/`market_book_get` if the broker exposes it.

- [ ] **Step 5: Repoint/restart MT5 MCP and recorder, then verify data arrival**

Update their terminal path/config to the branded IC Markets terminal only after preserving existing unit/config backups. Restart the affected services, verify active state and journals, then verify recorder database tick/book row counts increase across a timed interval. Keep prior MetaQuotes data separate.

- [ ] **Step 6: Run full relevant test suite and live operator health**

Run: `./venv/bin/pytest -q runtime/test_operator_*.py runtime/test_full_operator_tools.py runtime/test_claude_operator_mcp_server.py runtime/test_vps_ops_openai_tools.py`
Expected: PASS. Then verify EIROS Operator MCP, independent VPS root channel, noVNC viewer, MT5 MCP and recorder service health.

- [ ] **Step 7: Commit any acceptance-only config/code fixes**

If no code/config defect was found, make no empty commit. If a defect was fixed after a failing regression test, commit only those files with a message describing the defect.

## Self-Review Mapping

- Full root/filesystem: Task 1 + existing `root_exec`, exposed in Task 6.
- Full `DISPLAY=:99` view/control and serialized mutations: Task 2, exposed/tested in Task 6.
- Model-visible image content: Task 6 uses FastMCP `Image` rather than base64-only JSON.
- Secret metadata/redaction/non-argv desktop/process injection: Task 3, exposed in Task 6.
- Persistent interactive root PTY: Task 4, exposed in Task 6.
- Automatic rollback of critical changes: Task 5, deployed/used in Task 6.
- Independent root/noVNC recovery paths: Global Constraints + Task 6 deployment procedure.
- IC Markets no-human-desktop acceptance: Task 7.
