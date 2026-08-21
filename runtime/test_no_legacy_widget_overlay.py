from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "runtime" / "pulse_anchor.html"


def test_path_read_text_is_not_overlaid() -> None:
    direct = TARGET.open("r", encoding="utf-8").read()
    via_path = TARGET.read_text(encoding="utf-8")
    assert via_path == direct
    assert "JS_STARTED" in via_path
    assert "runtime_pulse_anchor_v4.html" not in via_path


def test_sitecustomize_does_not_patch_widget_metadata() -> None:
    source = (ROOT / "sitecustomize.py").read_text(encoding="utf-8")
    assert "Path.read_text = _guarded_path_read_text" not in source
    assert "FastMCP.resource = guarded_resource" not in source


if __name__ == "__main__":
    test_path_read_text_is_not_overlaid()
    test_sitecustomize_does_not_patch_widget_metadata()
    print("legacy widget overlay disabled: ok")
