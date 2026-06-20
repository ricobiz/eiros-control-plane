#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${EIROS_SOURCE_REPO:-/srv/eiros-workspace}"
REF="${EIROS_RESTORE_REF:-origin/main}"
PREFIX="${EIROS_PREFIX:-/opt/eiros-control-plane}"
DATA_DIR="${EIROS_DATA_DIR:-/var/lib/eiros}"
USER_NAME="${EIROS_USER:-eiros}"
TUNNEL_ID="${EIROS_TUNNEL_ID:-tunnel_6a348638523c8191bdf391bd2582609d}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="/root/eiros-restore-backup-${STAMP}"
WORK_DIR="$(mktemp -d /tmp/eiros-restore.XXXXXX)"
SOURCE_DIR="${WORK_DIR}/source"
LOG_FILE="/tmp/eiros-restore-${STAMP}.log"
STEP="preflight"

cleanup() {
  rm -rf "$WORK_DIR"
}

last_error() {
  local rc=$?
  printf '\nRESTORE=FAILED\nSTEP=%s\n' "$STEP"
  if [[ -f "$LOG_FILE" ]]; then
    printf 'DETAIL=' 
    tail -n 8 "$LOG_FILE" | tr '\n' ' ' | cut -c1-1200
    printf '\n'
  fi
  printf 'BACKUP=%s\n' "$BACKUP_DIR"
  cleanup
  exit "$rc"
}

trap last_error ERR
trap cleanup EXIT

run_quiet() {
  "$@" >>"$LOG_FILE" 2>&1
}

[[ $EUID -eq 0 ]] || { echo "Run as root"; exit 1; }
[[ -d "$REPO/.git" ]] || { echo "Missing Git checkout: $REPO"; exit 1; }
command -v git >/dev/null
command -v python3 >/dev/null
command -v tunnel-client >/dev/null

mkdir -p "$BACKUP_DIR" "$SOURCE_DIR" "$(dirname "$LOG_FILE")"
chmod 700 "$BACKUP_DIR"

STEP="fetch-main"
run_quiet git -C "$REPO" fetch origin main --prune
RESTORE_COMMIT="$(git -C "$REPO" rev-parse "$REF")"
git -C "$REPO" archive "$REF" | tar -x -C "$SOURCE_DIR"
[[ -f "$SOURCE_DIR/deploy/install.py" ]]
[[ -f "$SOURCE_DIR/runtime/server_v2.py" ]]

STEP="backup"
for path in \
  /etc/eiros \
  /etc/eiros-tunnel.env \
  /etc/systemd/system/eiros-tunnel.service \
  /etc/systemd/system/eiros-tunnel.service.d \
  /etc/systemd/system/eiros-worker.service \
  /etc/systemd/system/eiros-root-broker.service \
  /home/eiros/.config/tunnel-client; do
  if [[ -e "$path" ]]; then
    target="$BACKUP_DIR${path}"
    mkdir -p "$(dirname "$target")"
    cp -a "$path" "$target"
  fi
done

STEP="canonical-env"
id "$USER_NAME" >/dev/null 2>&1 || useradd --system --create-home --shell /bin/bash "$USER_NAME"
install -d -o root -g "$USER_NAME" -m 750 /etc/eiros

ENV_SOURCE=""
if [[ -s /etc/eiros/tunnel.env ]]; then
  ENV_SOURCE=/etc/eiros/tunnel.env
elif [[ -s /etc/eiros-tunnel.env ]]; then
  ENV_SOURCE=/etc/eiros-tunnel.env
else
  echo "No tunnel credentials file found" >>"$LOG_FILE"
  false
fi

set -a
# shellcheck disable=SC1090
source "$ENV_SOURCE"
set +a
[[ -n "${CONTROL_PLANE_API_KEY:-}" ]] || { echo "CONTROL_PLANE_API_KEY missing" >>"$LOG_FILE"; false; }

umask 027
cat > /etc/eiros/tunnel.env <<EOF
CONTROL_PLANE_API_KEY=${CONTROL_PLANE_API_KEY}
TUNNEL_CLIENT_PROFILE_DIR=/home/${USER_NAME}/.config/tunnel-client
EOF
chown root:"$USER_NAME" /etc/eiros/tunnel.env
chmod 640 /etc/eiros/tunnel.env

STEP="restore-profile"
PROFILE_DIR="/home/${USER_NAME}/.config/tunnel-client"
install -d -o "$USER_NAME" -g "$USER_NAME" -m 700 "$PROFILE_DIR"
cat > "$PROFILE_DIR/eiros.yaml" <<EOF
config_version: 1
control_plane:
  base_url: "https://api.openai.com"
  tunnel_id: "${TUNNEL_ID}"
  api_key: "env:CONTROL_PLANE_API_KEY"
health:
  listen_addr: "127.0.0.1:0"
  url_file: "/home/${USER_NAME}/tunnel-health.url"
admin_ui:
  open_browser: false
log:
  level: info
  format: json
mcp:
  commands:
    - channel: main
      command: "${PREFIX}/venv/bin/python -m runtime.server_v2"
EOF
chown "$USER_NAME":"$USER_NAME" "$PROFILE_DIR/eiros.yaml"
chmod 600 "$PROFILE_DIR/eiros.yaml"

# Drop-ins from the failed HTTP-rescue experiments override the restored unit.
rm -f /etc/systemd/system/eiros-tunnel.service.d/override.conf

STEP="install-release"
run_quiet python3 "$SOURCE_DIR/deploy/install.py" \
  --source "$SOURCE_DIR" \
  --prefix "$PREFIX" \
  --data-dir "$DATA_DIR" \
  --user "$USER_NAME" \
  --display-name EIROS \
  --channel default \
  --widget-domain ""

STEP="enable-operator-mode"
python3 - <<PY >>"$LOG_FILE" 2>&1
import json
import os
from pathlib import Path

path = Path(${DATA_DIR@Q}) / "config" / "instance.json"
value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
features = value.setdefault("features", {})
features["root_broker"] = True
security = value.setdefault("security", {})
security["shell_mode"] = "operator"
security["allow_local_shell_tasks"] = True
tmp = path.with_suffix(".tmp")
tmp.parent.mkdir(parents=True, exist_ok=True)
tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
os.chmod(tmp, 0o600)
os.replace(tmp, path)
PY
chown -R "$USER_NAME":"$USER_NAME" "$DATA_DIR/config"

STEP="restart-services"
systemctl daemon-reload >>"$LOG_FILE" 2>&1
systemctl enable --now eiros-root-broker.service >>"$LOG_FILE" 2>&1
systemctl enable --now eiros-worker.service >>"$LOG_FILE" 2>&1
rm -f "/home/${USER_NAME}/tunnel-health.url"
systemctl restart eiros-tunnel.service >>"$LOG_FILE" 2>&1

STEP="verify-runtime"
runuser -u "$USER_NAME" -- env \
  HOME="/home/${USER_NAME}" \
  EIROS_DATA_DIR="$DATA_DIR" \
  PYTHONPATH="$PREFIX/current" \
  "$PREFIX/venv/bin/python" - <<'PY' >>"$LOG_FILE" 2>&1
from runtime.server_v2 import health
value = health()
assert value.get("ok") is True, value
print(value)
PY

STEP="wait-tunnel"
READY=0
for _ in $(seq 1 45); do
  if systemctl is-active --quiet eiros-tunnel.service \
     && [[ -s "/home/${USER_NAME}/tunnel-health.url" ]]; then
    BASE="$(cat "/home/${USER_NAME}/tunnel-health.url")"
    BASE="${BASE%/}"
    if curl -fsS "$BASE/healthz" >/dev/null 2>&1 \
       && curl -fsS "$BASE/readyz" >/dev/null 2>&1; then
      READY=1
      break
    fi
  fi
  sleep 1
done
[[ "$READY" == 1 ]]

STEP="verify-services"
for service in eiros-root-broker.service eiros-worker.service eiros-tunnel.service; do
  systemctl is-active --quiet "$service"
done

STEP="disable-temporary-rescue"
systemctl disable --now eiros-rescue-agent.service eiros-rescue-mcp.service >>"$LOG_FILE" 2>&1 || true
if [[ -f /etc/caddy/conf.d/eiros-rescue.caddy ]]; then
  mv /etc/caddy/conf.d/eiros-rescue.caddy "$BACKUP_DIR/eiros-rescue.caddy.disabled"
  caddy validate --config /etc/caddy/Caddyfile >>"$LOG_FILE" 2>&1 && systemctl reload caddy >>"$LOG_FILE" 2>&1 || true
fi

trap - ERR
printf 'RESTORE=OK\n'
printf 'COMMIT=%s\n' "$RESTORE_COMMIT"
printf 'RELEASE=%s\n' "$(readlink -f "$PREFIX/current")"
printf 'TUNNEL_READY=1\n'
printf 'SHELL_MODE=operator\n'
printf 'ROOT_BROKER=active\n'
printf 'BACKUP=%s\n' "$BACKUP_DIR"
