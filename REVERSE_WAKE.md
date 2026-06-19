# EIROS Reverse Wake Channel

## Goal
Allow an event created on the VPS (for example, text entered in a remote terminal) to originate a new turn in the currently open ChatGPT conversation without Rico manually sending a message.

## Important boundary
The Secure MCP Tunnel is request/response transport. It does not itself push unsolicited messages into a ChatGPT conversation.

## Proposed architecture

1. Add an MCP render tool `open_pulse` with `_meta.ui.resourceUri = ui://eiros/pulse.html`.
2. The tool renders a compact MCP App iframe in the target ChatGPT conversation.
3. The iframe keeps an adaptive event loop while mounted.
4. It calls `tools/call` over the MCP Apps host bridge to invoke `poll_events(cursor, widget_session_id)` through the existing Secure MCP Tunnel.
5. A VPS command such as `eiros-signal "text"` appends a durable event with a monotonic sequence number.
6. When `poll_events` returns a new event, the iframe:
   - calls `ui/update-model-context` with the event payload;
   - calls `ui/message` with a machine-readable prompt containing event ID, source, timestamp, and text.
7. ChatGPT posts that component-authored message in the same conversation, creating the next model turn.
8. EIROS handles the event, performs actions through MCP tools, then calls `ack_event(event_id, result)`.

## Reliability
- Durable append-only event log.
- Monotonic sequence/cursor.
- At-least-once delivery with idempotent acknowledgement.
- Widget heartbeat and leader lease to avoid duplicate messages from multiple mounted widgets.
- Adaptive polling: fast while work is active, exponential backoff while idle.
- Backlog catch-up after app/widget suspension.
- Hard event and turn limits plus kill switch.

## Scope
Expected to work while the ChatGPT app and widget are mounted and allowed to run. It is not guaranteed while iOS suspends the app or when the widget is unmounted. On resume, queued events should be replayed.

## First proof
1. Render `open_pulse` in the current chat.
2. Run `eiros-signal "REMOTE_PING_001"` on the VPS.
3. Confirm the widget posts a `ui/message` into this exact conversation.
4. Confirm EIROS responds and acknowledges the same event ID.
