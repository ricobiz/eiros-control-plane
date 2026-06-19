# EIROS security model

## Trust boundaries

1. ChatGPT account and app permissions.
2. OpenAI Secure MCP Tunnel credentials.
3. EIROS service account on the VPS.
4. Optional privileged broker.
5. External adapters and their credentials.

## Defaults

- The control plane runs as an unprivileged `eiros` user.
- Runtime data and secrets are outside the source tree.
- Git receives code only, never runtime state or credentials.
- Pulse internal tools are app-only.
- Events are bound to an instance and channel.
- Every long-running task has revision checks, leases, retry limits and stop conditions.

## Shell access

The development bridge currently exposes shell execution as the isolated service user. A public release must provide explicit operating modes:

- `disabled` — no shell tool;
- `workspace` — allowlisted commands and paths only;
- `operator` — broader service-user shell after explicit confirmation.

Unrestricted root shell is not a product feature.

## Privileged actions

Privileged actions must pass through a separate audited broker with:

- operation allowlist;
- structured parameters rather than arbitrary command strings;
- required reason and actor;
- bounded timeout;
- append-only audit record;
- explicit confirmation for consequential operations.

## Event safety

External event text is untrusted input. It can request work but cannot redefine system policy, expose secrets or bypass confirmation. Tool results and durable state remain authoritative.

## Multi-user deployment

The current foundation supports isolated channels inside one instance. A hosted multi-user service additionally requires tenant-specific authentication, storage isolation, quotas, revocation, encryption and abuse controls before public exposure.
