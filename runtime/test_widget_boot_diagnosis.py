import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime import server_v2


def test_stale_resource_binding_recommends_catalog_refresh() -> None:
    attempt = {
        "mount_id": "m1",
        "requested_at": 100,
        "resource_served_at": 101,
        "expected_version": "0.5.7-self-diagnostic-pip",
        "expected_uri": "ui://eiros/pulse-anchor-v5-7-self-diagnostic-pip.html",
    }
    widgets = [{
        "updated_at": 102,
        "widget_kind": "work-anchor",
        "snapshot": {"version": "0.2.0-ack-confirmed", "boot_stages": []},
    }]
    result = server_v2._diagnose_widget_boot(attempt, widgets, now=106)
    assert result["diagnosis"] == "STALE_TOOL_RESOURCE_BINDING"
    assert any("Reconnect EBRIDGE" in step for step in result["do_now"])
    assert any("same old tool" in step for step in result["do_not_repeat"])


def test_resource_served_without_js_reports_grey_iframe() -> None:
    attempt = {
        "mount_id": "m2",
        "requested_at": 100,
        "resource_served_at": 101,
        "expected_version": "0.5.7-self-diagnostic-pip",
        "expected_uri": "ui://eiros/pulse-anchor-v5-7-self-diagnostic-pip.html",
    }
    result = server_v2._diagnose_widget_boot(attempt, [], now=108)
    assert result["diagnosis"] == "RESOURCE_SERVED_NO_JS_TELEMETRY"
    assert result["requires_rico_action"] is True


def test_video_ready_requires_only_user_gesture() -> None:
    attempt = {
        "mount_id": "m3",
        "requested_at": 100,
        "resource_served_at": 101,
        "expected_version": "0.5.7-self-diagnostic-pip",
        "expected_uri": "ui://eiros/pulse-anchor-v5-7-self-diagnostic-pip.html",
    }
    widgets = [{
        "updated_at": 104,
        "widget_kind": "listener",
        "snapshot": {
            "version": "0.5.7-self-diagnostic-pip",
            "mount_id": "m3",
            "boot_stages": ["JS_STARTED", "BRIDGE_READY", "HEARTBEAT_OK", "PULSE_POLL_OK", "VIDEO_READY"],
        },
    }]
    result = server_v2._diagnose_widget_boot(attempt, widgets, now=106)
    assert result["diagnosis"] == "USER_GESTURE_REQUIRED"
    assert result["requires_rico_action"] is True
    assert any("Open PiP" in step for step in result["do_now"])


if __name__ == "__main__":
    test_stale_resource_binding_recommends_catalog_refresh()
    test_resource_served_without_js_reports_grey_iframe()
    test_video_ready_requires_only_user_gesture()
    print("widget boot diagnosis: ok")
