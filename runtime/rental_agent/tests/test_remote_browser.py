from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from runtime.rental_agent.remote_browser import RemoteBrowserController


@dataclass
class FakePageState:
    url: str
    title: str = "Listing"
    html: str = "<html><body>listing</body></html>"
    frame: bytes = b"jpeg-one"


class FakeRuntime:
    def __init__(self) -> None:
        self.pages: dict[str, FakePageState] = {}
        self.next_page = 0
        self.events: list[tuple] = []
        self.closed = False

    def open(self, url: str) -> str:
        self.next_page += 1
        handle = f"page-{self.next_page}"
        self.pages[handle] = FakePageState(url=url)
        self.events.append(("open", url, handle))
        return handle

    def snapshot(self, handle: str) -> dict[str, object]:
        page = self.pages[handle]
        return {
            "url": page.url,
            "title": page.title,
            "html": page.html,
            "jpeg": page.frame,
        }

    def click(self, handle: str, x: float, y: float) -> None:
        self.events.append(("click", handle, x, y))
        self.pages[handle].frame = b"jpeg-clicked"

    def scroll(self, handle: str, dx: float, dy: float) -> None:
        self.events.append(("scroll", handle, dx, dy))
        self.pages[handle].frame = b"jpeg-scrolled"

    def key(self, handle: str, key: str) -> None:
        self.events.append(("key", handle, key))

    def text(self, handle: str, text: str) -> None:
        self.events.append(("text", handle, text))

    def back(self, handle: str) -> None:
        self.events.append(("back", handle))

    def reload(self, handle: str) -> None:
        self.events.append(("reload", handle))

    def close_page(self, handle: str) -> None:
        self.events.append(("close_page", handle))
        self.pages.pop(handle, None)

    def load_page(self, url: str) -> dict[str, str]:
        self.events.append(("load_page", url))
        return {"url": url, "title": "Fetched", "html": "<html>fetched</html>"}

    def close(self) -> None:
        self.closed = True


def make_controller(tmp_path: Path) -> tuple[RemoteBrowserController, FakeRuntime]:
    runtime = FakeRuntime()
    controller = RemoteBrowserController(
        profile_dir=tmp_path / "browser" / "search",
        runtime_factory=lambda: runtime,
        viewport={"width": 1280, "height": 900},
    )
    return controller, runtime


def test_open_source_reuses_same_live_session(tmp_path: Path) -> None:
    controller, runtime = make_controller(tmp_path)
    try:
        first = controller.open_source("batdongsan")
        second = controller.open_source("batdongsan")
        assert first["session_id"] == second["session_id"]
        assert [event[0] for event in runtime.events].count("open") == 1
        assert first["frame_seq"] == 1
    finally:
        controller.shutdown()


def test_frame_omits_unchanged_base64_after_seen_sequence(tmp_path: Path) -> None:
    controller, _ = make_controller(tmp_path)
    try:
        opened = controller.open_source("nhatot")
        frame = controller.frame(str(opened["session_id"]), after_seq=int(opened["frame_seq"]))
        assert frame["frame_changed"] is False
        assert frame["frame_seq"] == opened["frame_seq"]
        assert frame["screenshot_base64"] == ""
    finally:
        controller.shutdown()


def test_pointer_scroll_and_text_are_serialized_to_page(tmp_path: Path) -> None:
    controller, runtime = make_controller(tmp_path)
    try:
        opened = controller.open_source("batdongsan")
        session_id = str(opened["session_id"])
        controller.input(session_id, "pointer", x=640, y=450, user_gesture=True)
        controller.input(session_id, "scroll", delta_x=0, delta_y=320, user_gesture=True)
        controller.input(session_id, "text", text="hello", user_gesture=True)
        kinds = [event[0] for event in runtime.events]
        assert "click" in kinds
        assert "scroll" in kinds
        assert "text" in kinds
    finally:
        controller.shutdown()


def test_verification_blocks_agent_input_but_accepts_user_gesture(tmp_path: Path) -> None:
    controller, runtime = make_controller(tmp_path)
    try:
        opened = controller.open_source("batdongsan")
        session_id = str(opened["session_id"])
        handle = next(iter(runtime.pages))
        runtime.pages[handle].title = "Chờ một chút..."
        runtime.pages[handle].html = "<html>cf-chl- verify you are human</html>"
        controller.frame(session_id)
        with pytest.raises(PermissionError, match="user gesture"):
            controller.input(session_id, "pointer", x=200, y=300, user_gesture=False)
        result = controller.input(session_id, "pointer", x=200, y=300, user_gesture=True)
        assert result["session_id"] == session_id
        assert any(event[0] == "click" for event in runtime.events)
    finally:
        controller.shutdown()


def test_close_and_scout_loader_share_same_runtime(tmp_path: Path) -> None:
    controller, runtime = make_controller(tmp_path)
    try:
        opened = controller.open_source("nhatot")
        page = controller.load_page("https://example.test/listing")
        assert page.url == "https://example.test/listing"
        assert page.title == "Fetched"
        closed = controller.close(str(opened["session_id"]))
        assert closed["closed"] is True
        assert controller.status()["active_sessions"] == 0
        assert any(event[0] == "load_page" for event in runtime.events)
    finally:
        controller.shutdown()


def test_status_does_not_start_browser_runtime(tmp_path: Path) -> None:
    created = []

    def factory():
        created.append(True)
        return FakeRuntime()

    controller = RemoteBrowserController(
        profile_dir=tmp_path / "browser" / "search",
        runtime_factory=factory,
    )
    try:
        status = controller.status()
        assert status["active_sessions"] == 0
        assert status["thread_alive"] is False
        assert created == []
    finally:
        controller.shutdown()
