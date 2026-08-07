# EBRIDGE VPS Ops — OpenAI Control Plane Operator Design

Date: 2026-08-07
Owner: Rico
Operator: ChatGPT through Ebridge VPS Ops MCP
Status: User-approved direction; written spec pending review

## 1. Objective

Extend the existing `Ebridge VPS Ops` connector with a first-class, audited OpenAI Control Plane operator layer so ChatGPT can independently create, inspect, update, wire, start, stop, validate, and retire OpenAI MCP tunnels/runtimes/profiles on Rico's VPS without ever reading or returning the admin API key.

The goal is maximum practical operational autonomy for connector creation and lifecycle management while preserving two hard invariants:

1. secret values never enter MCP tool outputs, logs, git, or ChatGPT-visible text;
2. destructive removal operations are explicit and auditable so an accidental tool call cannot silently destroy a working connector.

The existing generic `root_exec` remains available for ordinary VPS administration, but OpenAI tunnel/runtime administration uses dedicated tools because the surrounding safety layer blocks secret-bearing shell workflows and because explicit typed tools are safer and easier to audit.

## 2. Existing environment

Current VPS Ops server: `runtime/vps_ops_server.py`.

Current characteristics:
- FastMCP server on `127.0.0.1:8790`.
- Existing allowlisted service/file/git tools.
- Existing unrestricted `root_exec` tool.
- Existing `tunnel-client` binary installed on the VPS.
- Existing EBRIDGE tunnel and tunnel profile must remain untouched unless a tool call explicitly targets them.
- Admin credential has been registered by Rico through a local secret reference. The model must never read the secret value.

## 3. Design decision

Implement a dedicated OpenAI Control Plane module behind Ebridge VPS Ops, with typed MCP tools exposed from `runtime/vps_ops_server.py` and implementation isolated in a focused helper module.

Create:
- `runtime/openai_control_plane.py` — tunnel-client command construction, scope resolution, redaction, audit writing, validation.
- `runtime/test_openai_control_plane.py` — unit/contract tests using a fake runner; no real tunnel mutation in automated tests.

Modify:
- `runtime/vps_ops_server.py` — register thin MCP wrappers only.
- `runtime/test_widget.py` or a focused VPS Ops contract test only if needed to verify tool registration; prefer a new focused test file rather than growing unrelated tests.

Runtime audit file:
- `/var/log/eiros/openai-control-plane.jsonl`

Secret reference default:
- `/etc/eiros/openai-admin.key`

The helper passes a **secret reference** to `tunnel-client` (for example `file:/etc/eiros/openai-admin.key`) or relies on the active admin profile. It never opens the secret file to return its content and never serializes environment variables containing key values.

## 4. Capability surface

### 4.1 Admin credential/profile status

`openai_admin_status()`

Returns only redacted capability state:
- whether the configured admin secret reference exists;
- whether an active tunnel-client admin profile exists;
- control-plane base URL;
- tunnel-client version;
- whether tunnel CRUD and runtime CRUD are available in the installed CLI.

Never returns:
- API key values;
- file contents;
- authorization headers;
- full environment dumps.

### 4.2 Tunnel inventory

`openai_tunnel_list(organization_id="", workspace_id="")`

`openai_tunnel_get(tunnel_id)`

These are read-only and require no confirmation. Results are normalized to stable JSON fields such as:
- tunnel id;
- name;
- description;
- organization/workspace attachments;
- lifecycle/status fields exposed by the installed tunnel-client;
- timestamps if available.

Unknown fields from future tunnel-client versions may be preserved under a bounded `raw_meta` object after secret/header redaction.

### 4.3 Tunnel creation

`openai_tunnel_create(name, description, organization_ids=None, workspace_ids=None, inherit_scope_from_tunnel="")`

Rules:
- no per-call human confirmation is required;
- if explicit org/workspace ids are supplied, use them;
- otherwise, if `inherit_scope_from_tunnel` is supplied, read that tunnel metadata and reuse its attachments;
- otherwise use a configured default scope only if one has been explicitly stored in non-secret VPS Ops configuration;
- never guess an organization/workspace id;
- return the new `tunnel_id` and normalized metadata only.

This allows ChatGPT to create future dedicated connectors independently.

### 4.4 Tunnel update

`openai_tunnel_update(tunnel_id, name=None, description=None, organization_ids=None, workspace_ids=None)`

No confirmation required. The tool may change metadata and attachments but must not silently delete the tunnel.

### 4.5 Tunnel deletion

`openai_tunnel_delete(tunnel_id, confirm_tunnel_id)`

Deletion is allowed, but requires `confirm_tunnel_id == tunnel_id` in the same tool call. This is a mechanical typo/accident guard, not a separate conversational approval ceremony. ChatGPT remains operationally autonomous once the target is intentionally specified.

The tool must refuse deletion of the current EBRIDGE tunnel if its id is marked protected in configuration unless `allow_protected=True` is added in a future explicitly approved design. v1 does not expose that override.

### 4.6 Runtime lifecycle

Expose installed tunnel-client runtime capabilities through typed tools:

- `openai_runtime_list(...)`
- `openai_runtime_get(runtime_or_alias)`
- `openai_runtime_create(alias, tunnel_id, mcp_server_url, organization_ids=None, workspace_ids=None, ...)`
- `openai_runtime_update(...)`
- `openai_runtime_delete(runtime_or_alias, confirm_runtime)`

Exact argument mapping follows the installed `tunnel-client runtimes ... --help` contract discovered during implementation. The MCP wrapper contract stays stable even if the CLI flags differ by installed version.

Creation/update requires no confirmation. Deletion uses the same same-value confirmation guard as tunnel deletion.

### 4.7 Local tunnel profile lifecycle

Expose local profile management required to connect one VPS MCP server to one OpenAI tunnel:

- `openai_profile_list()`
- `openai_profile_get(name)` — redacted; never returns secret values.
- `openai_profile_create(name, tunnel_id, mcp_server_url, health_listen_addr="127.0.0.1:0", health_url_file="")`
- `openai_profile_validate(name)` — runs `tunnel-client doctor`.
- `openai_profile_delete(name, confirm_name)`

Profiles are created under the canonical profile directory owned by the `eiros` service user, using `tunnel-client init`/profile commands rather than hand-writing unknown schema where possible.

### 4.8 Daemon/service lifecycle

Provide a bounded mechanism for dedicated tunnel daemons:

- `openai_tunnel_daemon_install(profile_name, service_name="")`
- `openai_tunnel_daemon_status(profile_name_or_service)`
- `openai_tunnel_daemon_start(...)`
- `openai_tunnel_daemon_restart(...)`
- `openai_tunnel_daemon_stop(...)`
- `openai_tunnel_daemon_remove(..., confirm_name)`

Generated services must be namespaced, for example `eiros-tunnel-rental-agent.service`, and must execute `tunnel-client run --profile <name>` as the existing `eiros` OS account. Service names and profile names are strictly validated to `[a-z0-9][a-z0-9-]{0,62}`.

Service removal requires same-value confirmation; start/stop/restart do not require conversational approval.

### 4.9 One-shot connector provisioning

Add a high-level orchestration tool:

`openai_connector_provision(alias, name, description, mcp_server_url, inherit_scope_from_tunnel="", organization_ids=None, workspace_ids=None)`

It performs an idempotent workflow:
1. validate admin capability and local MCP URL;
2. resolve scope;
3. reuse an existing tunnel/runtime/profile with the same managed alias when safe, otherwise create the missing pieces;
4. create/validate the local tunnel profile;
5. install/start the dedicated tunnel daemon;
6. run doctor/readiness checks;
7. return a compact connector readiness object containing ids, profile/service names, and next user action if ChatGPT connector activation is still required.

This is the primary tool ChatGPT should use for future connector creation. Lower-level tools remain available for repair and advanced operations.

## 5. Maximum-autonomy policy

The operator layer is intentionally permissive for non-destructive lifecycle work.

Allowed without per-action confirmation:
- list/get/status;
- create tunnels;
- update tunnel metadata/scope;
- create/update runtimes;
- create/validate profiles;
- install/start/stop/restart tunnel daemons;
- provision complete connector stacks;
- run doctor/readiness checks;
- repair a managed connector when the requested target is unambiguous.

Mechanical same-target confirmation required inside the tool arguments:
- delete tunnel;
- delete runtime;
- delete local profile;
- remove generated systemd tunnel service.

Protected infrastructure:
- the current EBRIDGE tunnel/profile/service are marked protected and are not deletable by v1 OpenAI Control Plane tools;
- ordinary `root_exec` remains outside this protection boundary, but the purpose-built tools never use it to bypass their own safeguards.

## 6. Secret handling

Secret handling is non-negotiable:

- admin secret value is never returned to Python callers, MCP responses, stdout/stderr, audit logs, or tests;
- prefer `file:/etc/eiros/openai-admin.key` or an active `tunnel-client admin-profile` secret reference;
- subprocesses receive only the reference/required environment, not a serialized environment dump;
- command results pass through a redactor before returning to MCP;
- redact common bearer/key patterns defensively even though tunnel-client should not print them;
- error messages are bounded and redacted;
- audit records contain operation type, target ids/aliases, success/failure, exit code, duration, and sanitized error category only.

## 7. Command execution boundary

`runtime/openai_control_plane.py` owns all tunnel-client execution.

It uses argv arrays with `shell=False`; no user input is interpolated into shell strings.

Validation:
- tunnel ids must match the installed tunnel-client format, currently expected as `tunnel_[a-z0-9]{32}`;
- aliases/profile/service suffixes use a strict lowercase slug validator;
- URLs must be `http://127.0.0.1:<port>/...`, `http://localhost:<port>/...`, or another explicitly allowlisted MCP origin for local provisioning;
- organization/workspace ids are treated as opaque identifiers but length/character bounded;
- list limits and output sizes are bounded.

## 8. Scope discovery

For maximum autonomy, the preferred scope strategy is inheritance from an existing known-good tunnel.

The helper can read metadata for the current EBRIDGE tunnel and reuse its organization/workspace attachments when provisioning a new dedicated connector. It stores only the source tunnel id / resolved ids in normal configuration; no secret is involved.

If scope cannot be resolved, the tool returns `needs_user_action: scope` instead of guessing.

## 9. Audit and observability

Every mutating control-plane action writes one JSONL audit event to `/var/log/eiros/openai-control-plane.jsonl`:

- timestamp;
- operation;
- target type;
- target id/alias;
- requested non-secret metadata;
- result status;
- tunnel-client exit code;
- duration_ms;
- sanitized error category.

Add:

`openai_control_plane_audit(limit=100)`

This is read-only and returns bounded recent events.

## 10. Failure handling

Stable error categories:
- `admin_not_configured`
- `admin_profile_invalid`
- `scope_required`
- `invalid_identifier`
- `invalid_local_mcp_url`
- `tunnel_not_found`
- `runtime_not_found`
- `profile_not_found`
- `protected_target`
- `confirmation_mismatch`
- `tunnel_client_error`
- `doctor_failed`
- `daemon_failed`
- `parse_error`

Raw CLI stderr may be included only after redaction and length bounding.

Idempotent high-level provisioning must distinguish `created`, `reused`, `updated`, and `repaired` components.

## 11. Testing

Test-first implementation.

Unit tests use a fake command runner and temporary audit/profile directories. They must verify:
- secret redaction;
- no secret value appears in argv/result/audit;
- tunnel id and slug validation;
- scope inheritance;
- tunnel create/update/list/get normalization;
- same-value delete confirmation;
- protected EBRIDGE target rejection;
- runtime/profile/daemon command construction;
- high-level idempotent provisioning behavior;
- failure category mapping;
- bounded/redacted audit reading.

A live smoke test is run only after the unit suite is green:
1. read admin status;
2. read the existing EBRIDGE tunnel metadata;
3. create a dedicated test/Rental tunnel;
4. get it back;
5. provision the `rental-agent` profile/daemon against `http://127.0.0.1:8794/mcp`;
6. validate readiness;
7. do not delete the live Rental tunnel because it is the intended production target.

## 12. Success condition

From ChatGPT, without Rico opening the OpenAI platform for routine connector work, the assistant can provision and operate a new dedicated MCP connector end-to-end using `Ebridge VPS Ops`: create the OpenAI tunnel, inherit the correct scope, wire a local MCP endpoint, install/start its tunnel daemon, validate readiness, inspect/repair it later, and manage additional connectors the same way — while never exposing the admin API key and while protecting the existing EBRIDGE control path from accidental deletion.
