from __future__ import annotations

import hashlib
import os
import subprocess
import threading
import time
from io import BytesIO
from typing import Sequence

from PIL import ImageGrab


class X11Backend:
    def __init__(self, display: str = ":99") -> None:
        self.display = display

    def _env(self) -> dict[str, str]:
        return {**os.environ, "DISPLAY": self.display}

    def capture_jpeg(self, region: Sequence[int] | None = None) -> tuple[bytes, tuple[int, int]]:
        image = ImageGrab.grab(xdisplay=self.display)
        if region is not None:
            if len(region) != 4:
                raise ValueError("region must contain left, top, right, bottom")
            image = image.crop(tuple(int(v) for v in region))
        out = BytesIO()
        image.convert("RGB").save(out, format="JPEG", quality=58, optimize=True)
        return out.getvalue(), image.size

    def windows(self) -> list[dict[str, object]]:
        proc = subprocess.run(
            ["xdotool", "search", "--onlyvisible", "--name", ".*"],
            env=self._env(),
            text=True,
            capture_output=True,
            check=False,
        )
        result: list[dict[str, object]] = []
        seen: set[str] = set()
        for raw in proc.stdout.splitlines():
            wid = raw.strip()
            if not wid or wid in seen:
                continue
            seen.add(wid)
            name = subprocess.run(
                ["xdotool", "getwindowname", wid],
                env=self._env(),
                text=True,
                capture_output=True,
                check=False,
            ).stdout.strip()
            result.append({"id": wid, "name": name})
        return result

    def focus(self, window_id: str) -> None:
        subprocess.run(
            ["xdotool", "windowactivate", "--sync", str(window_id)],
            env=self._env(),
            capture_output=True,
            check=True,
        )

    def run_input(self, argv: Sequence[str], stdin: bytes | None = None) -> None:
        subprocess.run(
            list(argv),
            env=self._env(),
            input=stdin,
            capture_output=True,
            check=True,
        )

    def clipboard_set(self, payload: bytes) -> None:
        subprocess.run(
            ["xclip", "-selection", "clipboard"],
            env=self._env(),
            input=payload,
            capture_output=True,
            check=True,
        )


class DesktopController:
    def __init__(self, display: str = ":99", backend=None) -> None:
        self.display = display
        self.backend = backend or X11Backend(display)
        self._lock = threading.RLock()
        self._hash = ""
        self._seq = 0
        self._size: tuple[int, int] | None = None

    def status(self) -> dict[str, object]:
        frame = self.capture()
        return {
            "display": self.display,
            "backend": type(self.backend).__name__,
            "frame_seq": frame["frame_seq"],
            "sha256": frame["sha256"],
            "width": frame["width"],
            "height": frame["height"],
        }

    def capture(self, region: Sequence[int] | None = None) -> dict[str, object]:
        jpeg, size = self.backend.capture_jpeg(region)
        digest = hashlib.sha256(jpeg).hexdigest()
        if region is None:
            self._size = size
        if digest != self._hash:
            self._hash = digest
            self._seq += 1
        return {
            "frame_seq": self._seq,
            "sha256": digest,
            "width": size[0],
            "height": size[1],
            "jpeg": jpeg,
        }

    def windows(self) -> list[dict[str, object]]:
        return self.backend.windows()

    def focus(self, window_id: str) -> None:
        with self._lock:
            self.backend.focus(window_id)

    def _validate_point(self, x: int, y: int) -> None:
        if self._size is None:
            self.capture()
        assert self._size is not None
        width, height = self._size
        if not (0 <= int(x) < width and 0 <= int(y) < height):
            raise ValueError(f"pointer coordinates are outside display {width}x{height}")

    def pointer(self, x: int, y: int, button: int = 1, clicks: int = 1) -> None:
        self._validate_point(x, y)
        with self._lock:
            self.backend.run_input(
                [
                    "xdotool",
                    "mousemove",
                    "--sync",
                    str(int(x)),
                    str(int(y)),
                    "click",
                    "--repeat",
                    str(max(1, int(clicks))),
                    str(int(button)),
                ]
            )

    def drag(self, x1: int, y1: int, x2: int, y2: int, button: int = 1) -> None:
        self._validate_point(x1, y1)
        self._validate_point(x2, y2)
        with self._lock:
            self.backend.run_input(
                [
                    "xdotool",
                    "mousemove",
                    str(int(x1)),
                    str(int(y1)),
                    "mousedown",
                    str(int(button)),
                    "mousemove",
                    "--sync",
                    str(int(x2)),
                    str(int(y2)),
                    "mouseup",
                    str(int(button)),
                ]
            )

    def scroll(self, amount: int) -> None:
        n = int(amount)
        if n == 0:
            return
        button = "4" if n < 0 else "5"
        with self._lock:
            self.backend.run_input(["xdotool", "click", "--repeat", str(abs(n)), button])

    def key(self, key: str) -> None:
        if not str(key):
            raise ValueError("key is required")
        with self._lock:
            self.backend.run_input(["xdotool", "key", "--clearmodifiers", str(key)])

    def text(self, text: str) -> None:
        payload = str(text).encode()
        if not payload:
            raise ValueError("text is required")
        with self._lock:
            self.backend.run_input(
                ["xdotool", "type", "--clearmodifiers", "--delay", "1", "--file", "-"],
                stdin=payload,
            )

    def clipboard_set(self, text: str) -> None:
        with self._lock:
            self.backend.clipboard_set(str(text).encode())

    def wait(self, after_seq: int, timeout_seconds: float = 10.0) -> dict[str, object]:
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        while time.monotonic() < deadline:
            frame = self.capture()
            if int(frame["frame_seq"]) > int(after_seq):
                return {
                    "changed": True,
                    "frame_seq": frame["frame_seq"],
                    "sha256": frame["sha256"],
                    "width": frame["width"],
                    "height": frame["height"],
                }
            time.sleep(0.2)
        return {"changed": False, "frame_seq": self._seq}
