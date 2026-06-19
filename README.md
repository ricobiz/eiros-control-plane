# EIROS Control Plane

Persistent execution body for a live ChatGPT conversation.

## Architecture

```text
ChatGPT conversation
  ↕ MCP
EIROS Bridge
  ↕ Secure MCP Tunnel
VPS
  ↕
Queue, worker, event log, files, shell, memory and adapters
```

## Components

- `runtime/server_v2.py` — MCP server and tools.
- `runtime/queue.py` — durable queue and lease engine.
- `runtime/worker.py` — adaptive scheduler worker.
- `runtime/events.py` — reverse-channel event store.
- `runtime/pulse_widget.html` — mounted reverse-wake UI.
- `runtime/boot_report.py` — startup reporting.
- `bin/eiros-signal` — terminal event command.
- `CORE.md` — identity and operating contract.
- `PROTOCOL.md` — continuation protocol.
- `REVERSE_WAKE.md` — reverse-channel design.

## Verified path

```text
VPS event
→ Secure MCP Tunnel
→ EIROS Pulse
→ new turn in the same ChatGPT conversation
→ acknowledgement
```

Runtime state, logs, credentials, locks and PID files are excluded from Git.
