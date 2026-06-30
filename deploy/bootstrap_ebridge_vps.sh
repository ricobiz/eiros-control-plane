#!/usr/bin/env bash
set -euo pipefail

# Bootstrap a fresh Ubuntu 24.04 x86_64 VPS into the EIROS/EBRIDGE primary server.
# Run as root. Do not paste API keys into chat.
# Required values can be supplied as environment variables or entered interactively:
#   OPENAI_API_KEY
#   EIROS_MAIN_TUNNEL_ID
#   EIROS_OPS_TUNNEL_ID

TUNNEL_CLIENT_VERSION="v0.0.9--context-conduit-topaz"
TUNNEL_CLIENT_URL="https://persistent.oaistatic.com/tunnel-client/v0.0.9--context-conduit-topaz/tunnel-client-v0.0.9--context-conduit-topaz-linux-amd64.zip"
REPO_URL="https://github.com/ricobiz/eiros-control-plane.git"
APP_ROOT="/opt/eiros-control-plane"
USER_NAME="eiros"

need_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "ERROR: run as root" >&2
    exit 1
  fi
}

prompt_secret() {
  local var_name="$1"
  local prompt="$2"
  local current="${!var_name:-}"
  if [[ -z "${current}" ]]; then
    read -rsp "${prompt}: " current
    echo
    export "${var_name}=${current}"
  fi
}

prompt_value() {
  local var_name="$1"
  local prompt="$2"
  local current="${!var_name:-}"
  if [[ -z "${current}" ]]; then
    read -rp "${prompt}: " current
    export "${var_name}=${current}"
  fi
}

write_tunnel_profile() {
  local profile_name="$1"
  local tunnel_id="$2"
  local command="$3"
  local health_file="$4"
  local profile_path="/home/${USER_NAME}/.config/tunnel-client/${profile_name}.yaml"

  python3 - "$profile_path" "$tunnel_id" "$command" "$health_file" <<'PY'
from pathlib import Path
import json
import os
import sys

profile_path, tunnel_id, command, health_file = sys.argv[1:]
api_key = os.environ["OPENAI_API_KEY"]
Path(profile_path).parent.mkdir(parents=True, exist_ok=True)
Path(profile_path).write_text(f'''config_version: 1
control_plane:
  base_url: "https://api.openai.com"
  tunnel_id: "{tunnel_id}"
  api_key: {json.dumps(api_key)}
health:
  listen_addr: "127.0.0.1:0"
  url_file: "{health_file}"
admin_ui:
  open_browser: false
log:
  level: info
  format: json
mcp:
  commands:
    - channel: main
      command: {json.dumps(command)}
''')
PY

  chown "${USER_NAME}:${USER_NAME}" "${profile_path}"
  chmod 0640 "${profile_path}"
}

write_service_files() {
  cat >/etc/systemd/system/eiros-root-broker.service <<EOF
[Unit]
Description=EIROS audited privileged operations broker
After=local-fs.target
Before=eiros-worker.service

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=${APP_ROOT}
ExecStart=${APP_ROOT}/venv/bin/python -m root.root_broker
Restart=always
RestartSec=3
RuntimeDirectory=eiros
RuntimeDirectoryMode=0750
NoNewPrivileges=false
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/run /var/log/eiros /etc/systemd/system /etc/ssh /etc/ufw
CapabilityBoundingSet=CAP_CHOWN CAP_DAC_OVERRIDE CAP_FOWNER CAP_SETGID CAP_SETUID CAP_SYS_ADMIN CAP_NET_ADMIN

[Install]
WantedBy=multi-user.target
EOF

  cat >/etc/systemd/system/eiros-worker.service <<EOF
[Unit]
Description=EIROS durable scheduler worker
After=network-online.target eiros-root-broker.service
Wants=network-online.target
Requires=eiros-root-broker.service

[Service]
Type=simple
User=${USER_NAME}
Group=${USER_NAME}
WorkingDirectory=${APP_ROOT}
ExecStart=${APP_ROOT}/venv/bin/python -m runtime.worker
Restart=always
RestartSec=3
TimeoutStopSec=20
NoNewPrivileges=false
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/var/lib/eiros /home/${USER_NAME} ${APP_ROOT} /tmp

[Install]
WantedBy=multi-user.target
EOF

  cat >/etc/systemd/system/eiros-tunnel.service <<EOF
[Unit]
Description=EIROS OpenAI MCP Tunnel
After=network-online.target eiros-worker.service
Wants=network-online.target
Requires=eiros-worker.service

[Service]
Type=simple
User=${USER_NAME}
Group=${USER_NAME}
EnvironmentFile=/etc/eiros/tunnel.env
WorkingDirectory=${APP_ROOT}
ExecStart=/usr/local/bin/tunnel-client run --profile eiros --health.listen-addr 127.0.0.1:0 --health.url-file /home/${USER_NAME}/tunnel-health.url
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

  cat >/etc/systemd/system/eiros-vps-ops.service <<EOF
[Unit]
Description=EBRIDGE VPS Ops MCP Tunnel
After=network-online.target eiros-root-broker.service
Wants=network-online.target

[Service]
Type=simple
User=${USER_NAME}
Group=${USER_NAME}
EnvironmentFile=/etc/eiros/tunnel.env
WorkingDirectory=${APP_ROOT}
ExecStart=/usr/local/bin/tunnel-client run --profile eiros-vps-ops --health.listen-addr 127.0.0.1:0 --health.url-file /home/${USER_NAME}/vps-ops-tunnel-health.url
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
}

main() {
  need_root

  prompt_secret OPENAI_API_KEY "OpenAI API key"
  prompt_value EIROS_MAIN_TUNNEL_ID "Main EBRIDGE tunnel_id"
  prompt_value EIROS_OPS_TUNNEL_ID "VPS Ops tunnel_id"

  echo "== install packages =="
  apt update -y
  apt install -y ca-certificates curl git unzip python3-venv python3-pip

  echo "== install tunnel-client ${TUNNEL_CLIENT_VERSION} =="
  curl -fL -o /tmp/tunnel-client.zip "${TUNNEL_CLIENT_URL}"
  rm -rf /tmp/tunnel-client
  mkdir -p /tmp/tunnel-client
  unzip -o /tmp/tunnel-client.zip -d /tmp/tunnel-client >/dev/null
  find /tmp/tunnel-client -type f -name tunnel-client -exec install -m 0755 {} /usr/local/bin/tunnel-client \;
  /usr/local/bin/tunnel-client --help >/dev/null

  echo "== create user and dirs =="
  id "${USER_NAME}" >/dev/null 2>&1 || useradd -m -s /bin/bash "${USER_NAME}"
  install -d -o "${USER_NAME}" -g "${USER_NAME}" /var/lib/eiros /var/log/eiros /srv/eiros-workspace
  install -d -m 0750 /etc/eiros

  echo "== checkout repo =="
  if [[ -d "${APP_ROOT}/.git" ]]; then
    git -C "${APP_ROOT}" pull --ff-only || true
  else
    rm -rf "${APP_ROOT}"
    git clone "${REPO_URL}" "${APP_ROOT}"
  fi

  echo "== python env =="
  cd "${APP_ROOT}"
  python3 -m venv venv
  ./venv/bin/pip install -U pip
  if [[ -f requirements.txt ]]; then
    ./venv/bin/pip install -r requirements.txt
  fi
  ./venv/bin/pip install mcp

  echo "== env and profiles =="
  cat >/etc/eiros/tunnel.env <<EOF
CONTROL_PLANE_API_KEY=${OPENAI_API_KEY}
TUNNEL_CLIENT_PROFILE_DIR=/home/${USER_NAME}/.config/tunnel-client
EOF
  chmod 0600 /etc/eiros/tunnel.env
  chown -R "${USER_NAME}:${USER_NAME}" /etc/eiros

  write_tunnel_profile "eiros" "${EIROS_MAIN_TUNNEL_ID}" "${APP_ROOT}/venv/bin/python -m runtime.server_v2" "/home/${USER_NAME}/tunnel-health.url"
  write_tunnel_profile "eiros-vps-ops" "${EIROS_OPS_TUNNEL_ID}" "${APP_ROOT}/venv/bin/python -m runtime.vps_ops_server" "/home/${USER_NAME}/vps-ops-tunnel-health.url"

  echo "== permissions and compile =="
  chown -R "${USER_NAME}:${USER_NAME}" "${APP_ROOT}" /home/${USER_NAME}/.config/tunnel-client
  "${APP_ROOT}/venv/bin/python" -m py_compile "${APP_ROOT}/runtime/server_v2.py"
  "${APP_ROOT}/venv/bin/python" -m py_compile "${APP_ROOT}/runtime/vps_ops_server.py"

  echo "== services =="
  write_service_files
  systemctl daemon-reload
  systemctl enable --now eiros-root-broker.service eiros-worker.service eiros-tunnel.service eiros-vps-ops.service
  sleep 5

  echo "== status =="
  systemctl --no-pager --full status eiros-root-broker.service eiros-worker.service eiros-tunnel.service eiros-vps-ops.service | tail -120 || true
  echo "== journals =="
  journalctl -u eiros-tunnel.service -n 30 --no-pager || true
  journalctl -u eiros-vps-ops.service -n 30 --no-pager || true
  echo "== OK_EBRIDGE_BOOTSTRAP_DONE =="
}

main "$@"
