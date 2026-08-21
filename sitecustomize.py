"""EIROS Python startup compatibility module.

Legacy MCP Apps resource and Path.read_text monkeypatches were removed because
those process-wide overlays caused the running connector to serve stale widget
HTML and silently rewrote widget metadata/CSP behind server_v2.py.

This module is intentionally a no-op. All widget resources, CSP metadata and
version routing are now defined explicitly in runtime/server_v2.py.
"""
