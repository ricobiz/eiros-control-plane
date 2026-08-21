from __future__ import annotations

from runtime import server_v2


def test_widget_test_legacy_uri_is_a_true_sum_listener_alias(monkeypatch):
    calls: list[str] = []

    def fake_mark(uri: str):
        calls.append(uri)
        return {"mount_id": "mount-fixed"}

    monkeypatch.setattr(server_v2, "_mark_widget_resource_served", fake_mark)

    canonical = server_v2.widget_test_resource()
    legacy = server_v2.widget_test_resource_legacy()

    assert legacy == canonical
    assert calls == [server_v2.WIDGET_TEST_URI, server_v2.WIDGET_TEST_LEGACY_URI]

    resources = server_v2.mcp._resource_manager._resources
    canonical_resource = resources[server_v2.WIDGET_TEST_URI]
    legacy_resource = resources[server_v2.WIDGET_TEST_LEGACY_URI]
    assert legacy_resource.meta == canonical_resource.meta
    assert legacy_resource.title == canonical_resource.title
    assert legacy_resource.mime_type == canonical_resource.mime_type
