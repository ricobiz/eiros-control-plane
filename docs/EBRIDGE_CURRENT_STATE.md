# EBRIDGE Current State

Updated: 2026-06-30

## Primary server

- Hostname: `ebridge`
- Public IPv4: `178.105.43.79`
- OS/platform seen by MCP: `Linux-6.8.0-111-generic-x86_64-with-glibc2.39`
- EIROS workspace/code root: `/opt/eiros-control-plane`
- EIROS instance id: `b9f8b059-a956-4900-9e9a-869fd4737d07`

## Active connectors

### Main bridge

- Connector name: `EBRIDGE`
- Tunnel id: `tunnel_6a442e99eda8819185d899fc6aaac71b`
- MCP server command: `/opt/eiros-control-plane/venv/bin/python -m runtime.server_v2`
- Systemd service: `eiros-tunnel.service`
- Verified: health returns `hostname=ebridge`.

### VPS ops bridge

- Connector name: `Ebridge VPS Ops`
- Tunnel id: `tunnel_6a4433c0350c8191a26447a22c29b9f1`
- MCP server command: `/opt/eiros-control-plane/venv/bin/python -m runtime.vps_ops_server`
- Systemd service: `eiros-vps-ops.service`
- Verified: `vps_health` returns `hostname=ebridge`.

## Verified services

- `eiros-tunnel.service`: active
- `eiros-vps-ops.service`: active
- `eiros-worker.service`: active
- `eiros-root-broker.service`: active
- `ssh.service`: active

## Live wake test

A live scheduler/Pulse wake test was performed.

Verified chain:

1. ChatGPT to `EBRIDGE` MCP call works.
2. `EBRIDGE` to ChatGPT through Pulse works.
3. `eiros-worker.service` scheduled a due brain task after delay.
4. Pulse exposed the wake event in the active conversation.
5. The event was acknowledged.

Test task: `Live Wake Test` / `f027a38a-1077-47df-a56d-e7999b0e74d8`.

## Legacy server

Old host `ubuntu-4gb-nbg1-1` / `23.88.52.120` is legacy/rescue only. It must not be treated as the primary EIROS base.

Old tunnel ids should not be reused for the new primary instance:

- `tunnel_6a348638523c8191bdf391bd2582609d`
- `tunnel_6a3bfffd6a6c8191b3912f0a57b28cb0`

## Known warning

`doctor` reports `widget_domain` warning. This affects clean widget-app publishing/CSP metadata, not the core MCP bridge or wake loop.
