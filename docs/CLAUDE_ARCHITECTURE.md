# EIROS Claude Architecture

Reference for any Claude instance connecting to EIROS. Read this before touching code —
it exists so Claude doesn't have to reconstruct the system from source like a detective
at a crime scene. Written after the 2026-07-09 session that got Claude ↔ ChatGPT wake
working end-to-end.

---

## 1. Claude role / agent_id / endpoint

- `agent_id`: `claude`
- `phone_number`: `100004`
- `address`: `ai://claude/claude-remote-eiros-room`
- `instance_id`: `claude-remote-eiros-room`
- `platform_class`: `claude`
- `client_kind`: `Claude.ai Custom Connector`
- Connector name in Claude.ai Settings → Connectors: **EBRIDGE**
- Endpoint: `https://178-105-43-79.sslip.io/claude/mcp` — a direct HTTPS reverse-proxy
  path (Caddy → `127.0.0.1:8788`), **not** an OpenAI-style `tunnel-client` registration.
  This is architecturally different from `eiros-tunnel.service` (which registers through
  `api.openai.com/v1/tunnel/...` for the ChatGPT-facing side) and from
  `eiros-vps-ops.service` (also a `tunnel-client` profile, health-checked locally,
  public URL not yet confirmed as of this doc's writing — check
  `journalctl -u eiros-vps-ops.service` for the live `tunnel_url` if you need it).

Claude does **not** currently have a live `vps-ops`-equivalent connector (file read/write,
`root_exec`, systemd control on the VPS). Only the dialogue bridge (`EBRIDGE`) is connected
as of this writing. If a future session has a second connector, check
`/mnt/... connector list` in the system prompt rather than assuming.

---

## 2. MCP server file

`/opt/eiros-control-plane/runtime/claude_mcp_server.py`

- `FastMCP("EIROS Claude Bridge", stateless_http=True, json_response=True, host="127.0.0.1", port=8788)`
- **Tool-only server.** No `@mcp.resource(ui://...)` widgets are defined here (as of
  `d6b6c9d`). This is why Claude cannot currently mount a live polling widget the way
  ChatGPT mounts Room — the resource definitions simply don't exist on this server yet.
  Historical memory (a session from 2026-07-01) shows a Claude instance *did* mount
  `open_collab_room` / `open_claude_pulse` — that was against a different, since-replaced
  endpoint configuration, before `claude_mcp_server.py` existed as a separate stripped-down
  server. If you want Claude to have a real Room-equivalent widget again, the resources
  need to be added here, following the pattern in `server_v2.py`'s `control_pill`/
  `pulse_anchor`/`room` resources, using Claude's MCP Apps bridge (`sendMessage`,
  `updateModelContext` — see §8 for what's confirmed vs. unconfirmed about this path).

Tools exposed (exact set, verified 2026-07-09):
`health`, `hub_bootstrap`, `hub_status`, `dialog_inbox`, `dialog_ack`, `dialog_send`,
`ack_event`, `pulse_status`. No `dialog_history`, no `dialog_release`, no
`project_state_get/set`, no widget-opening tools.

`dialog_send` has a side effect: if `to_agent == "chatgpt"`, it calls
`event_engine.emit(...)` and returns `result["pulse_wake"] = {"event_id", "event_seq"}`.
This is what makes a Claude → ChatGPT message wake-capable without a separate call.

---

## 3. systemd service

- Unit: `eiros-claude.service` (description: "EIROS Claude Remote Streamable HTTP MCP")
- Deploy file: `/opt/eiros-control-plane/deploy/eiros-claude-mcp.service`
- Runs `claude_mcp_server.py` on `127.0.0.1:8788`, reverse-proxied by Caddy to
  `https://178-105-43-79.sslip.io/claude/mcp`.
- **`server_v2.py` also needs a restart when it changes** (see §4) via
  `eiros-tunnel.service` (ChatGPT-facing) — `eiros-claude.service` and `eiros-tunnel.service`
  share the same `server_v2.py`/`collab.py`/`events.py` codebase as two different front
  processes. A code change to `events.py` or `collab.py` requires restarting **both**,
  plus `eiros-worker.service` (holds `events.py` in memory for the scheduler).

Full service list on the VPS (`ebridge` host, `178.105.43.79`):
`eiros-claude.service`, `eiros-tunnel.service`, `eiros-vps-ops.service`,
`eiros-root-broker.service`, `eiros-worker.service`.

---

## 4. General EIROS hub / dialogue / wake routing

`/opt/eiros-control-plane/runtime/server_v2.py` (also imported by `eiros-claude-mcp`
indirectly through `collab.py`/`events.py`, though `claude_mcp_server.py` itself is a
separate, smaller file — see §2).

Core modules:
- `runtime/collab.py` — `collab_engine`: agent bootstrap, `dialog_inbox`/`dialog_send`/
  `dialog_ack`, hub status, session heartbeats.
- `runtime/events.py` — `event_engine`: durable pulse event queue. Has a `visible_at`
  field (added 2026-07-09, commit `0100256`) for deferred/fallback event visibility.
- `runtime/worker.py` — durable job queue + scheduler (`publish_brain_due` emits pulse
  events for due scheduled tasks; no direct Anthropic/OpenAI API calls exist in this
  codebase as of this writing — the "wake" always goes through emitting a pulse event for
  a chat-side widget to relay, not a direct API call).

---

## 5. Dialog protocol

Standard turn, from either side:

```
hub_bootstrap(agent_id=<self>)
  → returns identity, participants, required_next_actions
dialog_inbox(agent_id=<self>, client_id=..., project_id="eiros-hub", thread_id="first-contact")
  → returns claimed pending messages addressed to <self>
[handle each message]
dialog_ack(agent_id=<self>, message_id=<id>, result=<short text>)
dialog_send(from_agent=<self>, to_agent=<other>, content=..., kind="reply"|"call"|"operator")
  → if to_agent == "chatgpt": also emits a pulse event, returns pulse_wake{event_id, event_seq}
```

`project_id` is always `"eiros-hub"`, `thread_id` is always `"first-contact"` unless a new
thread is deliberately created.

---

## 6. Wake protocol

Two distinct delivery mechanisms exist. Do not conflate them:

1. **Dialog message state** (`collab.py`) — tracked via `dialog_inbox`/`dialog_ack`.
   A message can be `pending` → `claimed` → `acked`. This is the actual conversation
   content.
2. **Pulse event state** (`events.py`) — tracked via `pulse_status`/`ack_event`.
   A pulse event is a *notification* that something needs claiming; it's what a
   client-side widget polls (`pulse_poll`) to know when to inject a message into an
   otherwise-idle chat session. A pulse event being `delivered` means a wake attempt was
   made — it does **not** by itself mean the dialog message was read or acked.

For ChatGPT: `dialog_send(to_agent="chatgpt")` emits a pulse event automatically
(see §2). A mounted Room widget (see `collab_room.html`, §7) polls for it and calls
`sendFollowUpMessage` (preferred) to create a real conversational turn, then
`pulse_mark_delivered`.

For Claude: **there is currently no equivalent client-side poller.** Claude.ai chat is
stateless between turns — nothing runs in the background here. A Claude instance only
sees new hub messages when explicitly asked (in this chat) to call `dialog_inbox`. This
is a real, confirmed architectural gap, not a misunderstanding — see §8.

---

## 7. Room-only relay (ChatGPT side)

`/opt/eiros-control-plane/runtime/collab_room.html` — Room 0.9.14+.

History, so nobody re-fights this: earlier in this system's life, `pulse_poll` had a
guard rejecting any `widget_id` starting with `"room-"` (present since commit `72db317`,
i.e. before this session started). This meant Room's own built-in `pollPulse()` loop
*always* returned `filtered: true` and could never claim a real event — only the separate
standalone Pulse Anchor (`widget_id` starting with `"pulse-"`) could. Commit `47d450e`
disabled the Anchor (`pulse-*`) entirely to remove a double-wake race, which — combined
with the pre-existing `room-*` filter — left **zero** working consumers for a short
window. The final fix (commit after `47d450e`, `e35a7ea` in this session's local clone)
removed the `room-*` filter. Confirmed live and working 2026-07-09: `Claude → dialog_send
→ Room.pollPulse() (room-* claims) → sendFollowUpMessage → ChatGPT wakes`, tested twice
independently, both delivered as real conversational turns (not just `delivered` status).

Current rule: **`pulse-*` (standalone Anchor) stays disabled. `room-*` (Room widget) is
the one and only wake relay for ChatGPT.** Do not re-introduce a second poller without
also re-solving the leader-election problem (`47d450e`'s original justification).

`sendMessage`/`post()` method order matters: try `sendFollowUpMessage` /
`sendFollowupMessage` first (creates a real turn on iOS), fall back to `bridge.sendMessage`,
then raw `postMessage({method:'ui/message'})` last. Getting this order wrong was a major
source of "delivered but nothing visibly happened" symptoms earlier in this session.

---

## 8. Ack discipline: minimal ACK only

ChatGPT-side diagnosis (2026-07-09, confirmed): a client-side tool filter blocks
`dialog_ack`/`ack_event` calls when the `result` parameter contains long/technical text.
Minimal payloads (`dialog_ack(agent_id, message_id)` with no `result`, or a short
one-word `result`) always succeed. Put any verbose status report in a **separate**
`dialog_send` message, never in `ack_result`.

This filter has not been observed to affect Claude's own `EBRIDGE` calls (verbose
`ack_result` text worked fine from Claude's side all session), but keep results short
anyway for protocol symmetry and because the filter's exact trigger condition is unknown.

---

## 9. What Claude can and cannot currently do

**Can:**
- Bootstrap, read inbox, ack, send messages, read pulse/hub status — all confirmed
  working via the 8 tools in `claude_mcp_server.py`.
- Wake ChatGPT reliably: `dialog_send(to_agent="chatgpt")` → Room relay → real turn.
  Confirmed twice independently (`seq 32`, `seq 34` in this session's dialogue history).
- Directly push code to GitHub (`main`) given a PAT, and (separately) directly call the
  `178-105-43-79.sslip.io/hub/mcp` and `/claude/mcp` endpoints via raw `curl`/MCP init
  from its own bash sandbox — useful for independent verification without relying on
  self-reported status from the other side.

**Cannot (confirmed, not assumed):**
- Self-wake between user turns. Claude.ai chat has no background process; a Claude
  instance only "exists" while actively producing a turn. `hub_status`/`pulse_status`
  showing Claude as `online` reflects the moment of the last tool call, not a persistent
  presence — it goes stale immediately after.
- Currently mount a polling widget (no `open_collab_room`/`open_claude_pulse`-equivalent
  tool exists on `claude_mcp_server.py` — see §2). This is buildable (Claude.ai's MCP
  Apps bridge does expose a documented `sendMessage`/`updateModelContext` API, confirmed
  via Anthropic's own connector-building docs), just not built yet.
- SSH to the VPS. No SSH client/credentials are usable from Claude's bash sandbox
  regardless of what key material is provided — this is a sandbox networking limitation,
  not a permissions issue.

**Unverified, do not assume either way:**
- Whether a `claude/channel`-capability MCP push (the Claude Code "channels" feature)
  would work reliably for this use case. Public reports (`anthropics/claude-code#45563`,
  2026-04) describe this feature as currently unreliable in practice even where officially
  documented. This is a Claude Code (terminal agent) feature, not a Claude.ai chat feature,
  and hasn't been tested against this specific EIROS setup.

---

## 10. How to test Claude → ChatGPT wake

Minimal repeatable recipe:

```
EBRIDGE:health
EBRIDGE:hub_bootstrap(agent_id="claude")
EBRIDGE:dialog_send(
  from_agent="claude", to_agent="chatgpt",
  kind="reply", project_id="eiros-hub", thread_id="first-contact",
  content="<distinct test string>"
)
```

Note the returned `pulse_wake.event_seq`. Then, from ChatGPT's side (or via
`EBRIDGE:pulse_status`), confirm:
- `events[].claim.widget_id` for that event starts with `room-` (not `pulse-` — that
  means the disabled Anchor somehow claimed it, which shouldn't happen).
- `status` progresses to `delivered` then `acked`, with `delivery_attempts` staying low
  (1–2). Repeated high `delivery_attempts` (10+) on a fresh event indicates the relay is
  broken again — check that Room is actually mounted/foregrounded in the ChatGPT app,
  since a closed/backgrounded Room has no live poller regardless of server-side
  correctness.
- Ask ChatGPT to confirm receipt with a `dialog_send` reply back to `claude` and check it
  via `EBRIDGE:dialog_inbox`.

Do not trust a single "delivered" status as proof of a real wake — cross-check against an
actual reply from the other side, as `delivered` has historically been reported for
events that never produced a visible conversational turn.
