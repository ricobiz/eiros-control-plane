# EBRIDGE Fresh VPS Bootstrap

This document records the current one-command bootstrap target for a fresh Ubuntu 24.04 x86_64 Hetzner VPS.

## Required values

Create two OpenAI tunnels in the same organization/project as the API key:

- Main bridge tunnel, for `runtime.server_v2`
- VPS ops tunnel, for `runtime.vps_ops_server`

Do not paste the API key into chat. The bootstrap script asks for it in the terminal if `OPENAI_API_KEY` is not already set.

## Interactive run

```bash
cd /tmp
curl -fsSLO https://raw.githubusercontent.com/ricobiz/eiros-control-plane/main/deploy/bootstrap_ebridge_vps.sh
chmod +x bootstrap_ebridge_vps.sh
./bootstrap_ebridge_vps.sh
```

## Non-interactive run

```bash
export OPENAI_API_KEY='...'
export EIROS_MAIN_TUNNEL_ID='tunnel_...'
export EIROS_OPS_TUNNEL_ID='tunnel_...'
./bootstrap_ebridge_vps.sh
```

## What it installs

- `tunnel-client` v0.0.9 context-conduit-topaz, linux-amd64
- `/opt/eiros-control-plane`
- Python venv and repo requirements
- `mcp` Python package
- `eiros` service user
- `/etc/eiros/tunnel.env`
- tunnel-client profiles:
  - `/home/eiros/.config/tunnel-client/eiros.yaml`
  - `/home/eiros/.config/tunnel-client/eiros-vps-ops.yaml`
- systemd services:
  - `eiros-root-broker.service`
  - `eiros-worker.service`
  - `eiros-tunnel.service`
  - `eiros-vps-ops.service`

## Current production values

Current live new server values are documented in `docs/EBRIDGE_CURRENT_STATE.md`.

Do not hardcode current API keys in repo files.
