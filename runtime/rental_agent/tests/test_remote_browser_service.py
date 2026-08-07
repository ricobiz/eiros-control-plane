from pathlib import Path

from runtime.rental_agent.browser import BrowserPage
from runtime.rental_agent.db import RentalDatabase
from runtime.rental_agent.service import RentalService


class FakeRemoteBrowser:
    def __init__(self) -> None:
        self.calls = []

    def status(self):
        return {"available": True, "backend": "fake-remote", "active_sessions": 0, "sources": ["batdongsan", "nhatot"]}

    def open_source(self, source: str):
        self.calls.append(("open", source))
        return {"session_id": "rbs_test", "source": source, "frame_seq": 1, "screenshot_base64": "abc"}

    def frame(self, session_id: str, after_seq: int = 0):
        self.calls.append(("frame", session_id, after_seq))
        return {"session_id": session_id, "frame_seq": 2, "screenshot_base64": "def"}

    def input(self, session_id: str, event_type: str, **kwargs):
        self.calls.append(("input", session_id, event_type, kwargs))
        return {"session_id": session_id, "frame_seq": 3, "screenshot_base64": "ghi"}

    def close(self, session_id: str):
        self.calls.append(("close", session_id))
        return {"session_id": session_id, "closed": True}

    def load_page(self, url: str) -> BrowserPage:
        self.calls.append(("load_page", url))
        return BrowserPage(url=url, final_url=url, title="Shared", html="<html>shared</html>")


def make_service(tmp_path: Path, remote: FakeRemoteBrowser) -> RentalService:
    return RentalService(
        RentalDatabase(tmp_path / "rental.db"),
        browser_profile_dir=tmp_path / "browser" / "search",
        remote_browser_controller=remote,
    )


def test_service_remote_browser_methods_delegate_to_controller(tmp_path: Path) -> None:
    remote = FakeRemoteBrowser()
    service = make_service(tmp_path, remote)
    opened = service.browser_open("batdongsan")
    framed = service.browser_frame("rbs_test", after_seq=1)
    acted = service.browser_input("rbs_test", "scroll", delta_y=250, user_gesture=True)
    closed = service.browser_close("rbs_test")
    assert opened["session_id"] == "rbs_test"
    assert framed["frame_seq"] == 2
    assert acted["frame_seq"] == 3
    assert closed["closed"] is True
    assert [call[0] for call in remote.calls[:4]] == ["open", "frame", "input", "close"]


def test_scout_browser_worker_uses_same_remote_runtime_loader(tmp_path: Path) -> None:
    remote = FakeRemoteBrowser()
    service = make_service(tmp_path, remote)
    worker = service.scout_engine.browser_worker
    assert worker is not None
    page = worker.loader("https://example.test/a")
    assert page.title == "Shared"
    assert ("load_page", "https://example.test/a") in remote.calls


def test_legacy_snapshot_and_click_reuse_remote_session(tmp_path: Path) -> None:
    remote = FakeRemoteBrowser()
    service = make_service(tmp_path, remote)
    shot = service.browser_snapshot("nhatot")
    clicked = service.browser_click("nhatot", 100, 200)
    assert shot["session_id"] == "rbs_test"
    assert clicked["session_id"] == "rbs_test"
    assert any(call[0] == "input" and call[2] == "pointer" for call in remote.calls)
