from __future__ import annotations

import os
import secrets
import subprocess
from pathlib import Path

PUBLIC_BASE = "https://178-105-43-79.sslip.io"
TOKEN_FILE = Path("/etc/eiros/claude-operator.token")
URL_FILE = Path("/etc/eiros/claude-operator.url")
SNIPPET_FILE = Path("/etc/nginx/snippets/eiros-claude-operator.conf")
NGINX_CONFIGS = (
    Path("/etc/nginx/sites-enabled/claude-sslip.conf"),
    Path("/etc/nginx/sites-available/claude-sslip.conf"),
)
INCLUDE_LINE = "    include /etc/nginx/snippets/eiros-claude-operator.conf;\n"


def load_or_create_token() -> str:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    if TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    else:
        token = secrets.token_urlsafe(48)
    if len(token) < 32:
        raise RuntimeError("Claude operator capability token is unexpectedly short")
    TOKEN_FILE.write_text(token + "\n", encoding="utf-8")
    os.chmod(TOKEN_FILE, 0o600)
    return token


def render_snippet(token: str) -> str:
    return f'''# EIROS Claude Operator capability. Treat this path as a bearer secret.\nlocation = /operator-{token}/mcp {{\n    proxy_pass http://127.0.0.1:8794/mcp;\n    proxy_http_version 1.1;\n    proxy_set_header Host 127.0.0.1:8794;\n    proxy_set_header X-Real-IP $remote_addr;\n    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n    proxy_set_header X-Forwarded-Proto $scheme;\n    proxy_set_header Connection \"\";\n    proxy_buffering off;\n    proxy_cache off;\n    proxy_read_timeout 3600s;\n    proxy_send_timeout 3600s;\n    add_header X-Accel-Buffering no;\n    access_log off;\n}}\n'''


def ensure_include(path: Path) -> None:
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    if INCLUDE_LINE.strip() in text:
        return
    marker = "    location / {\n"
    if marker not in text:
        raise RuntimeError(f"cannot place Claude operator include in {path}")
    path.write_text(text.replace(marker, INCLUDE_LINE + "\n" + marker, 1), encoding="utf-8")


def main() -> None:
    token = load_or_create_token()
    SNIPPET_FILE.parent.mkdir(parents=True, exist_ok=True)
    SNIPPET_FILE.write_text(render_snippet(token), encoding="utf-8")
    os.chmod(SNIPPET_FILE, 0o600)

    for config in NGINX_CONFIGS:
        ensure_include(config)

    url = f"{PUBLIC_BASE}/operator-{token}/mcp"
    URL_FILE.write_text(url + "\n", encoding="utf-8")
    os.chmod(URL_FILE, 0o600)

    subprocess.run(["nginx", "-t"], check=True)
    subprocess.run(["systemctl", "reload", "nginx"], check=True)
    print("Claude operator capability route configured")
    print(f"Connector URL stored in: {URL_FILE}")
    print("Capability URL was not printed")


if __name__ == "__main__":
    main()
