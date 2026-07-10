from __future__ import annotations

import os
import secrets
import subprocess
from pathlib import Path

ROOT = Path("/opt/eiros-control-plane")
TEMPLATE = ROOT / "deploy/claude-sslip.nginx.template.conf"
LIVE_CONFIG = Path("/etc/nginx/sites-available/claude-sslip.conf")
ETC_TOKEN = Path("/etc/eiros/claude-vps-ops.token")
WORKSPACE_TOKEN = ROOT / "runtime/.claude_vps_ops_route_key"
URL_FILE = Path("/etc/eiros/claude-vps-ops.url")
PUBLIC_BASE = "https://178-105-43-79.sslip.io"
PLACEHOLDER = "__VPS_OPS_CAPABILITY__"


def load_or_create_token() -> str:
    ETC_TOKEN.parent.mkdir(parents=True, exist_ok=True)

    if ETC_TOKEN.exists():
        token = ETC_TOKEN.read_text(encoding="utf-8").strip()
    elif WORKSPACE_TOKEN.exists():
        token = WORKSPACE_TOKEN.read_text(encoding="utf-8").strip()
    else:
        token = secrets.token_urlsafe(48)

    if len(token) < 32:
        raise RuntimeError("Claude VPS Ops capability token is unexpectedly short")

    ETC_TOKEN.write_text(token + "\n", encoding="utf-8")
    os.chmod(ETC_TOKEN, 0o600)
    return token


def main() -> None:
    token = load_or_create_token()
    template = TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in template:
        raise RuntimeError("nginx capability placeholder missing")

    rendered = template.replace(PLACEHOLDER, token)
    LIVE_CONFIG.write_text(rendered, encoding="utf-8")
    os.chmod(LIVE_CONFIG, 0o644)

    url = f"{PUBLIC_BASE}/vps-ops-{token}/mcp"
    URL_FILE.write_text(url + "\n", encoding="utf-8")
    os.chmod(URL_FILE, 0o600)

    subprocess.run(["nginx", "-t"], check=True)
    subprocess.run(["systemctl", "reload", "nginx"], check=True)

    print("Claude VPS Ops capability route configured")
    print(f"Connector URL stored in: {URL_FILE}")
    print("The capability URL was not printed and must never be committed")


if __name__ == "__main__":
    main()
