import pytest

from runtime.vps_operator.desktop import DesktopController


class FakeBackend:
    def __init__(self):
        self.frame = b"A"
        self.events = []

    def capture_jpeg(self, region=None):
        return self.frame, (1440, 900)

    def windows(self):
        return [{"id": "11", "name": "Demo"}]

    def focus(self, window_id):
        self.events.append(("focus", str(window_id)))

    def run_input(self, argv, stdin=None):
        self.events.append((tuple(argv), stdin))

    def clipboard_set(self, payload):
        self.events.append(("clipboard", payload))


def test_capture_sequence_changes_only_when_frame_changes() -> None:
    backend = FakeBackend()
    ctl = DesktopController(backend=backend)
    a = ctl.capture()
    b = ctl.capture()
    backend.frame = b"B"
    c = ctl.capture()
    assert (a["frame_seq"], b["frame_seq"], c["frame_seq"]) == (1, 1, 2)
    assert c["jpeg"] == b"B"


def test_text_uses_xdotool_file_stdin_not_argv() -> None:
    backend = FakeBackend()
    ctl = DesktopController(backend=backend)
    ctl.text("hello world")
    argv, stdin = backend.events[-1]
    assert argv[-2:] == ("--file", "-")
    assert "hello world" not in " ".join(argv)
    assert stdin == b"hello world"


def test_pointer_rejects_coordinates_outside_display() -> None:
    ctl = DesktopController(backend=FakeBackend())
    with pytest.raises(ValueError, match="outside display"):
        ctl.pointer(-1, 20)
    with pytest.raises(ValueError, match="outside display"):
        ctl.pointer(1440, 20)
