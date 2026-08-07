from __future__ import annotations

import re
from pathlib import Path
from typing import Any

PROFILE_NAME = "rental-agent"
PROFILE_DIR = Path("/home/eiros/.config/tunnel-client")
PROFILE_PATH = PROFILE_DIR / f"{PROFILE_NAME}.yaml"
LOCAL_MCP_URL = "http://127.0.0.1:8794/mcp"
HEALTH_URL_FILE = "/home/eiros/rental-tunnel-health.url"
_TUNNEL_RE = re.compile(r"^tunnel_[a-z0-9]{32}$")


def validate_tunnel_id(tunnel_id: str) -> str:
    value = tunnel_id.strip()
    if not _TUNNEL_RE.fullmatch(value):
        raise ValueError("tunnel_id must match tunnel_<32 lowercase letters or digits>")
    return value


def render_profile(
    tunnel_id: str,
    api_key_ref: str = "env:CONTROL_PLANE_API_KEY",
) -> str:
    value = validate_tunnel_id(tunnel_id)
    key_ref = api_key_ref.strip()
    if not key_ref.startswith("env:"):
        raise ValueError("api_key_ref must be an env: reference, never a raw key")
    return f'''config_version: 1
control_plane:
  base_url: "https://api.openai.com"
  tunnel_id: "{value}"
  api_key: "{key_ref}"
health:
  listen_addr: "127.0.0.1:0"
  url_file: "{HEALTH_URL_FILE}"
admin_ui:
  open_browser: false
log:
  level: info
  format: json
mcp:
  server_urls:
    - channel: main
      url: "{LOCAL_MCP_URL}"
'''


def redacted_tunnel_status(
    *,
    tunnel_id: str = "",
    runtime_key: str = "",
    profile_exists: bool = False,
) -> dict[str, Any]:
    return {
        "profile": PROFILE_NAME,
        "profile_exists": bool(profile_exists),
        "tunnel_id_configured": bool(tunnel_id.strip()),
        "runtime_key_configured": bool(runtime_key.strip()),
    }
