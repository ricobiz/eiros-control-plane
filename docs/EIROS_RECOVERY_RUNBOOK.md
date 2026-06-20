# EIROS Control Plane recovery runbook

This is the canonical source of truth for production recovery. A new chat branch must read it before changing infrastructure.

## Canonical architecture

Do not replace this with AppDeploy, Caddy, a public HTTP MCP, a rescue agent, or a new tunnel profile.

```text
ChatGPT native app
  -> OpenAI Secure MCP Tunnel
  -> tunnel_6a348638523c8191bdf391bd2582609d
  -> tunnel-client profile: eiros
  -> stdio child:
     /opt/eiros-control-plane/venv/bin/python -m runtime.server_v2
  -> PYTHONPATH=/opt/eiros-control-plane/current
  -> durable data=/var/lib/eiros
```

Production services:

- `eiros-root-broker.service`
- `eiros-worker.service`
- `eiros-tunnel.service`

Repository and paths:

- repository: `ricobiz/eiros-control-plane`
- branch: `main`
- VPS checkout: `/srv/eiros-workspace`
- production prefix: `/opt/eiros-control-plane`
- data directory: `/var/lib/eiros`
- known working baseline before later UI experiments: `6277a616c1259614736783340c83b643ac248535`

## Safety rules

1. Back up units, environment files, symlinks and install state before changing production.
2. Never delete `/var/lib/eiros` or old releases during recovery.
3. Never change the tunnel ID while recovering this connector.
4. Do not switch the canonical ChatGPT connector from stdio to public HTTP.
5. Run one diagnostic command at a time; do not give Rico giant blind scripts.
6. Verify the actual process command, not only `systemctl is-active`.

## Minimal first inspection

```bash
cd /srv/eiros-workspace
git config --global --add safe.directory /srv/eiros-workspace
git rev-parse HEAD
git status --short
git log --oneline -8
systemctl is-active eiros-root-broker.service eiros-worker.service eiros-tunnel.service
ps -eo pid,user,cmd | grep '[t]unnel-client run'
```

## Bootstrap stderr only

Replace `<release>` with the release being tested:

```bash
sudo -u eiros env \
  EIROS_DATA_DIR=/var/lib/eiros \
  PYTHONPATH=/opt/eiros-control-plane/releases/<release> \
  /opt/eiros-control-plane/venv/bin/python -m runtime.bootstrap \
  --display-name EIROS --channel default --json >/dev/null
```

This suppresses stdout and leaves the real traceback visible.

## Confirmed failures from 2026-06-21

### Release directory blocked Python imports

Symptom:

```text
No module named runtime.bootstrap
```

The module existed. The real cause was:

```text
/opt/eiros-control-plane/releases  root:root 750
```

The service user could not traverse the parent directory. Safe repair:

```bash
sudo chown root:eiros /opt/eiros-control-plane/releases
sudo chmod 0750 /opt/eiros-control-plane/releases
```

`deploy/install.py` must preserve this invariant before running bootstrap.

### Production virtualenv contained the wrong or incomplete MCP package

Symptom:

```text
ModuleNotFoundError: No module named 'mcp.server'
```

Repair used:

```bash
sudo /opt/eiros-control-plane/venv/bin/python -m pip install \
  --no-cache-dir --force-reinstall 'mcp==1.28.0'
```

Verification:

```bash
sudo -u eiros env PYTHONPATH=/opt/eiros-control-plane/current \
  /opt/eiros-control-plane/venv/bin/python -c \
  'from mcp.server.fastmcp import FastMCP; print("MCP SDK OK")'
```

### systemd was running a stale rescue profile

A service can be active while systemd still holds a deleted drop-in in memory. The wrong process was:

```text
tunnel-client run --profile eiros-rescue-http
```

Canonical process:

```text
tunnel-client run --profile eiros --health.listen-addr 127.0.0.1:0 \
  --health.url-file /home/eiros/tunnel-health.url
```

After restoring units:

```bash
sudo systemctl daemon-reload
sudo systemctl restart eiros-root-broker.service
sudo systemctl restart eiros-worker.service
sudo systemctl restart eiros-tunnel.service
```

## Recovery order

1. Create a timestamped backup.
2. Fix release-parent traversal permissions.
3. Test bootstrap against the candidate release.
4. Run offline doctor with the same `EIROS_DATA_DIR` and `PYTHONPATH`.
5. Atomically set `current` only after both tests pass.
6. Restore canonical unit files.
7. Run `systemctl daemon-reload`.
8. Start root broker, worker and tunnel in that order.
9. Confirm the tunnel process uses profile `eiros`.
10. Confirm the connector by calling `health` from ChatGPT.
11. Keep the backup until all checks pass.

## Cross-branch handoff

Start a fresh branch with:

```text
Read docs/EIROS_RECOVERY_RUNBOOK.md and docs/EIROS_CURRENT_HANDOFF.json.
Then call reconnect_context or core_snapshot. Do not redesign deployment.
```
