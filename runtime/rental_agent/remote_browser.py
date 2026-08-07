from __future__ import annotations

import base64
import hashlib
import queue
import threading
import time
import uuid
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from runtime.rental_agent.browser import BrowserPage, HANDOFF_SOURCES


DEFAULT_VIEWPORT = {"width": 1280, "height": 900}


def verification_required(html: str, title: str) -> bool:
    text = f"{title}\n{html}".lower()
    markers = (
        "captcha",
        "verify you are human",
        "verification required",
        "security check",
        "challenge-platform",
        "cf-chl-",
    )
    return any(marker in text for marker in markers)


class PlaywrightRuntime:
    def __init__(self, *, profile_dir: Path, headless: bool, viewport: dict[str, int]) -> None:
        from playwright.sync_api import sync_playwright

        self.profile_dir = Path(profile_dir)
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.headless = bool(headless)
        self.viewport = dict(viewport)
        self._playwright = sync_playwright().start()
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.profile_dir),
            headless=self.headless,
            viewport=self.viewport,
            locale="vi-VN",
            timezone_id="Asia/Ho_Chi_Minh",
            args=["--disable-dev-shm-usage"],
        )
        self._pages: dict[str, Any] = {}

    def open(self, url: str) -> str:
        page = self._context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=25_000)
        try:
            page.wait_for_load_state("networkidle", timeout=5_000)
        except Exception:
            pass
        handle = f"page_{uuid.uuid4().hex}"
        self._pages[handle] = page
        return handle

    def snapshot(self, handle: str) -> dict[str, object]:
        page = self._pages[handle]
        return {
            "url": page.url,
            "title": page.title(),
            "html": page.content(),
            "jpeg": page.screenshot(type="jpeg", quality=52, full_page=False),
        }

    def click(self, handle: str, x: float, y: float) -> None:
        self._pages[handle].mouse.click(float(x), float(y))
        self._pages[handle].wait_for_timeout(700)

    def scroll(self, handle: str, dx: float, dy: float) -> None:
        self._pages[handle].mouse.wheel(float(dx), float(dy))
        self._pages[handle].wait_for_timeout(250)

    def key(self, handle: str, key: str) -> None:
        self._pages[handle].keyboard.press(str(key))

    def text(self, handle: str, text: str) -> None:
        self._pages[handle].keyboard.insert_text(str(text))

    def back(self, handle: str) -> None:
        self._pages[handle].go_back(wait_until="domcontentloaded", timeout=20_000)

    def reload(self, handle: str) -> None:
        self._pages[handle].reload(wait_until="domcontentloaded", timeout=20_000)

    def close_page(self, handle: str) -> None:
        page = self._pages.pop(handle, None)
        if page is not None:
            page.close()

    def load_page(self, url: str) -> dict[str, str]:
        page = self._context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=25_000)
            try:
                page.wait_for_load_state("networkidle", timeout=5_000)
            except Exception:
                pass
            return {"url": page.url, "title": page.title(), "html": page.content()}
        finally:
            page.close()

    def close(self) -> None:
        try:
            self._context.close()
        finally:
            self._playwright.stop()


@dataclass(slots=True)
class _Session:
    session_id: str
    source: str
    handle: str
    frame_seq: int = 0
    frame_hash: str = ""
    verification_required: bool = False
    url: str = ""
    title: str = ""
    last_used_at: float = 0.0


@dataclass(slots=True)
class _Command:
    op: str
    kwargs: dict[str, object]
    future: Future[Any]


class RemoteBrowserController:
    def __init__(
        self,
        *,
        profile_dir: Path,
        runtime_factory: Callable[[], Any] | None = None,
        viewport: dict[str, int] | None = None,
        headless: bool = True,
        command_timeout: float = 45.0,
    ) -> None:
        self.profile_dir = Path(profile_dir)
        self.viewport = dict(viewport or DEFAULT_VIEWPORT)
        self.headless = bool(headless)
        self.command_timeout = float(command_timeout)
        self._runtime_factory = runtime_factory or (
            lambda: PlaywrightRuntime(
                profile_dir=self.profile_dir,
                headless=self.headless,
                viewport=self.viewport,
            )
        )
        self._queue: queue.Queue[_Command | None] = queue.Queue(maxsize=64)
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()
        self._closed = False

    def _ensure_thread(self) -> None:
        if self._closed:
            raise RuntimeError("remote browser controller is closed")
        if self._thread is not None and self._thread.is_alive():
            return
        with self._start_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._thread_main,
                name="rental-remote-browser",
                daemon=True,
            )
            self._thread.start()

    def _submit(self, op: str, **kwargs: object) -> Any:
        self._ensure_thread()
        future: Future[Any] = Future()
        self._queue.put(_Command(op=op, kwargs=dict(kwargs), future=future), timeout=2.0)
        return future.result(timeout=self.command_timeout)

    def _thread_main(self) -> None:
        runtime: Any | None = None
        sessions: dict[str, _Session] = {}
        source_sessions: dict[str, str] = {}
        try:
            runtime = self._runtime_factory()
            while True:
                command = self._queue.get()
                if command is None:
                    break
                if command.future.cancelled():
                    continue
                try:
                    result = self._dispatch(runtime, sessions, source_sessions, command.op, command.kwargs)
                except BaseException as exc:
                    command.future.set_exception(exc)
                else:
                    command.future.set_result(result)
        except BaseException as exc:
            while True:
                try:
                    command = self._queue.get_nowait()
                except queue.Empty:
                    break
                if command is not None and not command.future.done():
                    command.future.set_exception(exc)
        finally:
            if runtime is not None:
                for session in list(sessions.values()):
                    try:
                        runtime.close_page(session.handle)
                    except Exception:
                        pass
                try:
                    runtime.close()
                except Exception:
                    pass

    def _dispatch(
        self,
        runtime: Any,
        sessions: dict[str, _Session],
        source_sessions: dict[str, str],
        op: str,
        kwargs: dict[str, object],
    ) -> Any:
        if op == "open_source":
            source = str(kwargs["source"]).strip().lower()
            if source not in HANDOFF_SOURCES:
                raise ValueError(f"unsupported remote browser source: {source}")
            existing_id = source_sessions.get(source)
            if existing_id and existing_id in sessions:
                session = sessions[existing_id]
            else:
                handle = runtime.open(HANDOFF_SOURCES[source])
                session = _Session(
                    session_id=f"rbs_{uuid.uuid4().hex}",
                    source=source,
                    handle=handle,
                    last_used_at=time.time(),
                )
                sessions[session.session_id] = session
                source_sessions[source] = session.session_id
            return self._capture(runtime, session, after_seq=0, force_payload=True)

        if op == "frame":
            session = self._session(sessions, str(kwargs["session_id"]))
            return self._capture(
                runtime,
                session,
                after_seq=int(kwargs.get("after_seq", 0)),
                force_payload=False,
            )

        if op == "input":
            session = self._session(sessions, str(kwargs["session_id"]))
            event_type = str(kwargs["event_type"]).strip().lower()
            user_gesture = bool(kwargs.get("user_gesture", False))
            self._capture(runtime, session, after_seq=0, force_payload=False)
            if session.verification_required and not user_gesture:
                raise PermissionError("human verification requires a user gesture")
            if event_type == "pointer":
                x = float(kwargs.get("x", 0.0))
                y = float(kwargs.get("y", 0.0))
                if not (0 <= x < self.viewport["width"] and 0 <= y < self.viewport["height"]):
                    raise ValueError("pointer coordinates are outside browser viewport")
                runtime.click(session.handle, x, y)
            elif event_type == "scroll":
                runtime.scroll(
                    session.handle,
                    float(kwargs.get("delta_x", 0.0)),
                    float(kwargs.get("delta_y", 0.0)),
                )
            elif event_type == "key":
                key = str(kwargs.get("key", ""))
                if not key:
                    raise ValueError("key is required")
                runtime.key(session.handle, key)
            elif event_type == "text":
                text = str(kwargs.get("text", ""))
                if not text:
                    raise ValueError("text is required")
                runtime.text(session.handle, text)
            elif event_type == "back":
                runtime.back(session.handle)
            elif event_type == "reload":
                runtime.reload(session.handle)
            else:
                raise ValueError(f"unsupported browser input event: {event_type}")
            session.last_used_at = time.time()
            return self._capture(runtime, session, after_seq=0, force_payload=True)

        if op == "close":
            session_id = str(kwargs["session_id"])
            session = sessions.pop(session_id, None)
            if session is None:
                return {"session_id": session_id, "closed": False, "status": "session_not_found"}
            runtime.close_page(session.handle)
            source_sessions.pop(session.source, None)
            return {"session_id": session_id, "closed": True, "status": "closed"}

        if op == "status":
            return {
                "available": True,
                "backend": "playwright-thread",
                "profile_dir": str(self.profile_dir),
                "viewport": dict(self.viewport),
                "active_sessions": len(sessions),
                "sources": sorted(HANDOFF_SOURCES),
                "thread_alive": True,
            }

        if op == "load_page":
            payload = runtime.load_page(str(kwargs["url"]))
            return BrowserPage(
                url=str(kwargs["url"]),
                final_url=str(payload.get("url") or kwargs["url"]),
                title=str(payload.get("title") or ""),
                html=str(payload.get("html") or ""),
            )

        raise ValueError(f"unsupported remote browser command: {op}")

    @staticmethod
    def _session(sessions: dict[str, _Session], session_id: str) -> _Session:
        session = sessions.get(session_id)
        if session is None:
            raise KeyError(f"remote browser session not found: {session_id}")
        return session

    def _capture(
        self,
        runtime: Any,
        session: _Session,
        *,
        after_seq: int,
        force_payload: bool,
    ) -> dict[str, object]:
        snapshot = runtime.snapshot(session.handle)
        jpeg = bytes(snapshot.get("jpeg") or b"")
        digest = hashlib.sha256(jpeg).hexdigest() if jpeg else ""
        changed = digest != session.frame_hash
        if changed:
            session.frame_hash = digest
            session.frame_seq += 1
        session.url = str(snapshot.get("url") or "")
        session.title = str(snapshot.get("title") or "")
        html = str(snapshot.get("html") or "")
        session.verification_required = verification_required(html, session.title)
        session.last_used_at = time.time()
        include_payload = bool(jpeg) and (force_payload or (changed and session.frame_seq > int(after_seq)))
        return {
            "session_id": session.session_id,
            "source": session.source,
            "status": "needs_user_action" if session.verification_required else "ready",
            "verification_required": session.verification_required,
            "url": session.url,
            "title": session.title,
            "viewport": dict(self.viewport),
            "frame_seq": session.frame_seq,
            "frame_changed": bool(changed and session.frame_seq > int(after_seq)),
            "screenshot_mime": "image/jpeg",
            "screenshot_base64": base64.b64encode(jpeg).decode("ascii") if include_payload else "",
            "profile_persistent": True,
            "error": "human verification required" if session.verification_required else "",
        }

    def open_source(self, source: str) -> dict[str, object]:
        return self._submit("open_source", source=source)

    def frame(self, session_id: str, after_seq: int = 0) -> dict[str, object]:
        return self._submit("frame", session_id=session_id, after_seq=int(after_seq))

    def input(
        self,
        session_id: str,
        event_type: str,
        *,
        x: float = 0.0,
        y: float = 0.0,
        delta_x: float = 0.0,
        delta_y: float = 0.0,
        key: str = "",
        text: str = "",
        user_gesture: bool = False,
    ) -> dict[str, object]:
        return self._submit(
            "input",
            session_id=session_id,
            event_type=event_type,
            x=float(x),
            y=float(y),
            delta_x=float(delta_x),
            delta_y=float(delta_y),
            key=key,
            text=text,
            user_gesture=bool(user_gesture),
        )

    def close(self, session_id: str) -> dict[str, object]:
        return self._submit("close", session_id=session_id)

    def status(self) -> dict[str, object]:
        thread = self._thread
        if self._closed:
            return {
                "available": False,
                "backend": "playwright-thread",
                "profile_dir": str(self.profile_dir),
                "viewport": dict(self.viewport),
                "active_sessions": 0,
                "sources": sorted(HANDOFF_SOURCES),
                "thread_alive": False,
            }
        if thread is None or not thread.is_alive():
            return {
                "available": True,
                "backend": "playwright-thread",
                "profile_dir": str(self.profile_dir),
                "viewport": dict(self.viewport),
                "active_sessions": 0,
                "sources": sorted(HANDOFF_SOURCES),
                "thread_alive": False,
            }
        return self._submit("status")

    def load_page(self, url: str) -> BrowserPage:
        return self._submit("load_page", url=url)

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        thread = self._thread
        if thread is None:
            return
        try:
            self._queue.put(None, timeout=1.0)
        except queue.Full:
            pass
        thread.join(timeout=5.0)
