# Claude VPS Ops architecture

## Purpose

Give Claude a direct Streamable HTTP MCP endpoint for audited VPS operations without exposing the root-capable server on a predictable public route.

## Components

### ChatGPT VPS Ops path

- Service: `eiros-vps-ops.service`
- Process: OpenAI `tunnel-client`
- Profile: `eiros-vps-ops`
- ChatGPT connector name: `Ebridge_VPS_Ops`
- This is separate from the direct HTTP server.

### Direct VPS Ops MCP server

- Implementation: `runtime/vps_ops_server.py`
- Service: `eiros-vps-ops-http.service`
- Local endpoint: `http://127.0.0.1:8790/mcp`
- Transport: Streamable HTTP
- Runs as root because the toolset includes `root_exec`.

### Claude public route

- nginx template: `deploy/claude-sslip.nginx.template.conf`
- Generator: `deploy/configure_claude_vps_ops_route.py`
- Public origin: `https://178-105-43-79.sslip.io`
- The route is an exact capability URL:
  `https://178-105-43-79.sslip.io/vps-ops-<random-capability>/mcp`
- A generic `/vps-ops/mcp` route must never be present.
- nginx access logging is disabled for the capability location.

## Secret handling

- Primary token file: `/etc/eiros/claude-vps-ops.token`
- Generated connector URL: `/etc/eiros/claude-vps-ops.url`
- Temporary workspace fallback: `runtime/.claude_vps_ops_route_key`
- Secret files and rendered nginx configs are ignored by Git.
- Never paste the capability URL into source code, GitHub, logs, or EIROS dialogue history.

## Deployment

```bash
cd /opt/eiros-control-plane
sudo install -m 644 deploy/eiros-vps-ops-http.service /etc/systemd/system/eiros-vps-ops-http.service
sudo systemctl daemon-reload
sudo systemctl enable --now eiros-vps-ops-http.service
sudo python3 deploy/configure_claude_vps_ops_route.py
```

Then retrieve the URL locally on the VPS:

```bash
sudo cat /etc/eiros/claude-vps-ops.url
```

Add that URL as a separate Claude Custom Connector. Do not send the URL through the EIROS Room.

## Verification

Local MCP server:

```bash
curl -i http://127.0.0.1:8790/mcp \
  -H 'Accept: application/json, text/event-stream'
```

Expected: HTTP 200 with `content-type: text/event-stream`.

Security checks:

```bash
grep -RIn 'location /vps-ops/mcp' /etc/nginx/sites-enabled || true
grep -RIn 'proxy_pass http://127.0.0.1:8790/mcp' /etc/nginx/sites-enabled
```

The first command must return nothing. The second should only point to exact generated capability locations.

## Security boundary

This endpoint exposes root-capable operations. The capability URL is a bearer secret. Rotate it immediately if it is disclosed. A future hardening step is replacing the capability URL with standard OAuth or an authenticated zero-trust gateway.
