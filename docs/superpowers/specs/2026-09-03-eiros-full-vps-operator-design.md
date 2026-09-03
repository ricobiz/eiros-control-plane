# EIROS Full VPS Operator Design

## Status
Approved by Rico in chat on 2026-09-03.

## Goal
EIROS must be able to operate the dedicated EBRIDGE VPS end to end without requiring Rico to use noVNC, type credentials on a phone, move a remote mouse, or manually complete routine GUI dialogs. The scope is the whole VPS, not MT5 only.

The target loop is: inspect state -> choose shell/files/service/desktop/secret action -> execute -> verify result. Rico is only needed when an external product itself requires a non-delegable human action.

## Existing environment
The current stack already has the privileged foundation:
- canonical repo `/opt/eiros-control-plane`;
- aggregate operator MCP in `runtime/claude_operator_mcp_server.py`;
- privileged VPS tools in `runtime/vps_ops_server.py`;
- arbitrary root command execution through the existing operator path;
- direct filesystem/systemd/journal/Git/tunnel tools;
- graphical trading desktop on `DISPLAY=:99` using Xvfb, Openbox, x11vnc and noVNC;
- Wine applications, including IC Markets MT5, on the same display;
- an existing remote-browser controller pattern with frame/input sessions.

The missing pieces are a reliable model-facing desktop controller, persistent interactive terminals, and local secret injection.

## Architecture
Extend the existing EIROS Operator instead of creating a separate MT5 controller or parallel control plane.

```text
ChatGPT / EIROS
      |
      | private MCP
      v
EIROS Operator MCP
      |
      +-- existing privileged tools: root / files / git / systemd / network
      +-- PTY manager: persistent interactive processes
      +-- Desktop controller: DISPLAY=:99 frame + input + windows
      +-- Local secret broker: named secrets -> local injection only
```

The external path stays private. No public root, desktop-control, or secret endpoint is introduced.

## Authority model
### Root and filesystem
The operator retains unrestricted root administration of this dedicated VPS. It supports arbitrary commands plus direct read/stat/list/write/replace/patch/copy/move/mkdir/delete/chmod/chown/atomic-write filesystem operations without a path allowlist.

### Desktop
The operator controls the entire `DISPLAY=:99`, not a fixed application list. It can capture frames, enumerate/focus windows when detectable, move/click/double-click/right-click/drag/scroll, send keys and hotkeys, type text, manage clipboard where available, and wait for visual/window-state changes. This applies to MT5, cTrader, Wine dialogs, browsers, installers, terminals and future GUI apps.

noVNC remains as a human viewer/emergency path but is not the automation transport.

## Desktop controller
The controller runs locally on the VPS. It should prefer direct X11/Win32 interaction where reliable and use framebuffer/input as the universal fallback because Wine applications such as MT5 do not expose every logical control as a separate X11 window.

A persistent desktop session tracks display, frame sequence/hash, dimensions, focus metadata and last activity. Only one writer controls the desktop at a time; read-only snapshots may be concurrent.

Required capability surface:
- `desktop_status()`
- `desktop_frame(after_seq=0, region=None)`
- `desktop_windows()`
- `desktop_focus(window_id)`
- `desktop_pointer(...)`
- `desktop_drag(...)`
- `desktop_scroll(...)`
- `desktop_key(...)`
- `desktop_text(...)`
- `desktop_clipboard_set(...)` for non-secret text
- `desktop_wait(...)`

Every consequential GUI action is verified by a new frame or state check instead of assuming the input landed in the intended place.

## Persistent PTY
Keep `root_exec` for finite non-interactive commands and add a PTY manager for installers, prompts, REPLs, debuggers, ssh, package managers and long-running diagnostics.

Required operations:
- `pty_start(command="/bin/bash", cwd=...)`
- `pty_write(session_id, data)`
- `pty_read(session_id, after_seq=...)`
- `pty_resize(...)`
- `pty_signal(...)`
- `pty_close(...)`
- `pty_list()`

PTY output is bounded/paginated so a runaway process cannot flood tool responses.

## Secret broker
Use a dedicated root-owned store such as `/var/lib/eiros-operator/secrets/` with directory mode `0700` and secret files mode `0600`. Secret values are excluded from Git, ordinary diagnostic archives and returned tool payloads.

Required capabilities:
- list secret names/metadata, never values;
- create/replace/delete a named secret through an explicit secret path;
- report whether a secret exists;
- inject a named secret into the focused desktop field;
- execute a local process with named secrets supplied through environment/stdin/file descriptor when supported by the target.

Examples: `secret_type("icmarkets_demo_password")`, `secret_exec(..., env_from={...})`, `secret_stdin(...)`.

The design does not claim that plaintext can be hidden from a local target process that must consume it. The requirement is to avoid routine exposure in chat, argv, Git, command history, broad logs and model-visible tool output.

## Recovery without reducing authority
Safety is implemented as automatic recovery, not a broad command allowlist or routine human confirmation.

Before changing critical configuration, capture the previous file/state. Critical classes include SSH, firewall/routing/DNS, nginx/tunnel configuration serving the operator path, the operator service itself, and systemd units required for operator access.

For a control-plane or network change that could disconnect the operator:
1. stage a timed local rollback;
2. apply the change;
3. run service/connectivity health checks;
4. cancel rollback only after success.

`Ebridge_VPS_Ops.root_exec` should remain operationally independent from the new desktop controller where practical, so GUI failure does not remove root recovery. noVNC remains a separate human fallback.

## Audit and concurrency
Record tool name, timestamp, success/failure, duration, safe target metadata and rollback identifier. Never log secret values, password-field contents, tokens, private keys or whole secret-bearing environments.

Desktop mutations are serialized behind a lease-based lock so two clients cannot type/click simultaneously. Read-only inspection can be concurrent.

## Failure handling
If a desktop input has no observable effect, capture a new frame/window inventory before retrying; do not blindly repeat input into unknown focus. PTY timeouts do not silently destroy persistent sessions. Missing secrets report only the missing name. Failed critical changes trigger rollback and record the rollback result.

## Testing
Implementation follows TDD for new operator components.

Unit tests cover desktop session sequencing/locking, input validation, frame change detection, PTY lifecycle, bounded reads, secret metadata/redaction, absence of secret values in tool responses/logs, rollback state transitions and atomic configuration replacement.

Integration tests use a controlled target window/display to verify frame capture, focus, text, click, hotkey, scroll, drag, test-secret injection by effect only, PTY interaction and a reversible systemd/config transaction.

## First end-to-end acceptance test
The first real scenario is the current IC Markets demo login:
1. Rico performs no noVNC input.
2. EIROS inspects `DISPLAY=:99` itself.
3. EIROS opens/focuses the IC Markets MT5 login flow.
4. EIROS fills login and server fields.
5. EIROS injects the stored password through the secret broker.
6. EIROS submits login.
7. EIROS verifies through GUI/MT5/API state that the intended IC Markets demo account is connected.
8. EIROS starts/reconfigures MCP and market recording and verifies data arrival.

## Deployment
Implementation stays in the canonical repo and existing operator architecture. Desktop, PTY and secret functionality should be focused modules rather than one monolithic server file. Persistent helpers are owned by systemd and bind only to loopback or Unix sockets. Production services run from canonical `main`, not transient worktree paths.

## Non-goals
- Do not expose privileged administration publicly to the Internet.
- Do not remove noVNC as an emergency human path.
- Do not replace stable broker APIs with GUI automation when an API is better.
- Do not claim authority over systems outside the VPS/operator boundary.

## Acceptance criteria
The implementation is accepted when EIROS can, without Rico operating the remote desktop:
1. execute arbitrary root commands with bounded output;
2. read and mutate arbitrary VPS filesystem paths through direct tools;
3. create and interact with a persistent root PTY;
4. capture `DISPLAY=:99` into a model-visible frame;
5. enumerate/focus windows when detectable;
6. click, drag, scroll, type and send hotkeys;
7. store/reference named local secrets without returning values;
8. inject a named secret into a GUI field without exposing it in ordinary tool output/logs;
9. use a named secret for a local process without putting it in command argv;
10. stage/verify critical control-plane changes with automatic rollback;
11. retain independent root recovery if the desktop controller fails;
12. log into the IC Markets demo MT5 account and verify broker/feed state end to end without Rico using noVNC input.
