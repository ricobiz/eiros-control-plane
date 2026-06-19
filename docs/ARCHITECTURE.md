# EIROS architecture

## Product invariant

An external event can create a new model turn in an already mounted ChatGPT conversation through an MCP App, without inserting a separate model API between the user and ChatGPT.

```text
external event
→ durable EIROS event store
→ OpenAI Secure MCP Tunnel
→ mounted Pulse MCP App
→ ui/message
→ new turn in the same ChatGPT conversation
→ tool execution
→ durable acknowledgement
```

## Separation of concerns

- **ChatGPT conversation** — reasoning authority and conversational context.
- **EIROS control plane** — durable state, queue, scheduler, event routing and execution.
- **Pulse MCP App** — reverse delivery bridge mounted in one conversation.
- **Adapters** — browser, device, email, Git, APIs and future execution modules.

No adapter is the brain. No separate API model impersonates the conversation.

## Instance and channel binding

Every installation receives a persistent `instance_id`. Every Pulse and event belongs to a named `channel`.

A Pulse poll is accepted only when its instance identifier matches the server. Leaders, cursors and pending events are isolated per channel. Two conversations cannot consume each other's channel events accidentally.

## Delivery semantics

EIROS uses durable, at-least-once delivery:

1. Event is written atomically before delivery.
2. One Pulse widget holds a bounded leader lease for a channel.
3. An event receives a bounded delivery claim.
4. The widget posts `ui/message`.
5. Delivery is recorded.
6. The model acknowledges the event after handling it.
7. Expired claims are returned to pending state during maintenance.

A repeated event carries the same event ID, allowing deterministic deduplication.

## iOS boundary

When the ChatGPT application and mounted Pulse are active, external events can initiate a new turn. When iOS suspends or terminates the host application, JavaScript polling cannot run. EIROS therefore preserves events durably and delivers them after the Pulse becomes active again.

EIROS does not claim to bypass iOS process suspension or create native push notifications without an approved notification channel.

## Data separation

Code and runtime data are independent:

- code: immutable versioned release;
- data: `EIROS_DATA_DIR`;
- instance configuration: `config/instance.json`;
- queue and event state: runtime directory;
- secrets: external protected environment files, never Git.

An update may replace code but must not replace runtime data.

## Release gates

A release is valid only after:

- Python compilation;
- queue lease/revision tests;
- scheduler tests;
- clean-directory bootstrap test;
- instance mismatch rejection test;
- channel isolation test;
- live doctor check;
- MCP App contract inspection.
