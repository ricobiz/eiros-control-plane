# EBRIDGE VPS Ops OpenAI Control Plane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend Ebridge VPS Ops with audited, secret-safe OpenAI tunnel/runtime/profile/daemon lifecycle tools and a one-shot connector provisioner, then use them to create the dedicated Rental Agent tunnel.

**Architecture:** Keep `runtime/vps_ops_server.py` as a thin MCP wrapper and put all OpenAI control-plane behavior in `runtime/openai_control_plane.py`. The helper invokes the installed `tunnel-client` with argv arrays (`shell=False`), uses the already-registered admin secret reference without reading key material into MCP output, writes bounded JSONL audit events, and exposes stable Python methods that are independently unit tested with a fake runner. Live mutation happens only after the unit suite is green.

**Tech Stack:** Python 3.12, FastMCP, `subprocess`, `json`, `pathlib`, pytest, systemd, installed OpenAI `tunnel-client`.

## Global Constraints

- Admin API key values must never enter MCP responses, stdout/stderr returned to ChatGPT, audit logs, git, or tests.
- Existing EBRIDGE tunnel/profile/service is protected from deletion by purpose-built tools.
- Non-destructive create/update/start/stop/restart/provision operations require no per-action conversational confirmation.
- Destructive delete/remove operations require a same-target confirmation argument.
- `runtime/openai_control_plane.py` owns all `tunnel-client` execution and always uses argv arrays with `shell=False`.
- Tunnel ids match `tunnel_[a-z0-9]{32}`; managed aliases/profile/service suffixes match `[a-z0-9][a-z0-9-]{0,62}`.
- Local MCP provisioning URLs are restricted to loopback (`127.0.0.1`/`localhost`) HTTP endpoints unless an explicit allowlist is added later.
- Audit file is `/var/log/eiros/openai-control-plane.jsonl`; test code overrides it to a temporary path.
- Automated tests never create, update, or delete real OpenAI tunnels/runtimes.
- Existing dirty/uncommitted EIROS work outside files named in this plan must not be staged or modified.

---

## File Structure

- Create `runtime/openai_control_plane.py` — validation, runner abstraction, redaction, admin status, tunnel/runtime/profile/daemon operations, provisioning orchestration, audit.
- Create `runtime/test_openai_control_plane.py` — unit tests with a fake runner and temporary filesystem paths.
- Create `runtime/test_vps_ops_openai_tools.py` — FastMCP tool-registration/wrapper contract tests.
- Modify `runtime/vps_ops_server.py` — import one operator instance and expose typed wrappers only.
- Modify `deploy/eiros-vps-ops-http.service` only if the live service needs an explicit environment/profile path; prefer no change if the active tunnel-client admin profile is sufficient.
- Update `docs/superpowers/specs/2026-08-07-vps-ops-openai-control-plane-design.md` only if live CLI discovery reveals a real contract correction.

---

### Task 1: Core validation, runner, secret-safe status, and audit

**Files:**
- Create: `runtime/openai_control_plane.py`
- Test: `runtime/test_openai_control_plane.py`

**Interfaces:**
- Produces `CommandResult` dataclass.
- Produces `ControlPlaneError(category: str, message: str)`.
- Produces `OpenAIControlPlane(runner=None, audit_path=..., protected_tunnel_ids=None, protected_profile_names=None, protected_service_names=None)`.
- Produces methods `admin_status() -> dict`, `audit(limit=100) -> dict`.
- Internal helpers: `validate_tunnel_id`, `validate_slug`, `validate_local_mcp_url`, `redact_text`, `_run_tunnel_client(argv, timeout=...)`, `_write_audit(...)`.

- [ ] **Step 1: Write failing validation/redaction tests**

```python
from pathlib import Path
import pytest

from runtime.openai_control_plane import OpenAIControlPlane, ControlPlaneError, redact_text


def test_redact_text_removes_bearer_and_openai_key_material() -> None:
    raw = "Authorization: Bearer sk-admin-secret123 OPENAI_ADMIN_KEY=sk-admin-secret123"
    clean = redact_text(raw)
    assert "sk-admin-secret123" not in clean
    assert "[REDACTED]" in clean


def test_identifier_and_local_url_validation(tmp_path: Path) -> None:
    op = OpenAIControlPlane(audit_path=tmp_path / "audit.jsonl")
    assert op.validate_tunnel_id("tunnel_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    assert op.validate_slug("rental-agent") == "rental-agent"
    assert op.validate_local_mcp_url("http://127.0.0.1:8794/mcp") == "http://127.0.0.1:8794/mcp"
    with pytest.raises(ControlPlaneError) as exc:
        op.validate_local_mcp_url("https://evil.example/mcp")
    assert exc.value.category == "invalid_local_mcp_url"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `PYTHONPATH=. /opt/eiros-control-plane/venv/bin/python -m pytest -q runtime/test_openai_control_plane.py`

Expected: import/module failure because `runtime/openai_control_plane.py` does not exist.

- [ ] **Step 3: Implement minimal validation, redaction, runner, error type, and audit writer**

`redact_text()` must remove at least:
- `Authorization: Bearer ...` token material;
- values following `OPENAI_ADMIN_KEY=`, `CONTROL_PLANE_API_KEY=`, `OPENAI_API_KEY=`;
- `sk-...` style key-like values;
- any exact secret strings passed through an optional `extra_secrets` internal argument.

The default runner executes only `/usr/local/bin/tunnel-client` with `shell=False`, bounded timeout, and a minimal environment (`PATH`, `HOME=/home/eiros`, `LANG=C.UTF-8`). It must not dump the parent environment.

- [ ] **Step 4: Add failing admin-status/audit tests**

Use a `FakeRunner` that records argv and returns canned JSON/help output. Assert:
- `admin_status()` reports booleans like `secret_reference_configured`, `admin_profile_active`, `tunnel_crud_available`, `runtime_crud_available`;
- no key value appears anywhere in the returned structure;
- `_write_audit()` writes operation/target/result/exit/duration but no secret text;
- `audit(limit=...)` returns newest bounded records.

- [ ] **Step 5: Implement `admin_status()` and `audit()` and run Task 1 tests**

Run: `PYTHONPATH=. /opt/eiros-control-plane/venv/bin/python -m pytest -q runtime/test_openai_control_plane.py`

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

```bash
git add runtime/openai_control_plane.py runtime/test_openai_control_plane.py
git commit -m "feat: add secret-safe OpenAI control plane core"
```

---

### Task 2: Tunnel CRUD, scope inheritance, and protection

**Files:**
- Modify: `runtime/openai_control_plane.py`
- Modify: `runtime/test_openai_control_plane.py`

**Interfaces:**
- Adds `tunnel_list(organization_id="", workspace_id="") -> dict`.
- Adds `tunnel_get(tunnel_id: str) -> dict`.
- Adds `tunnel_create(name, description, organization_ids=None, workspace_ids=None, inherit_scope_from_tunnel="") -> dict`.
- Adds `tunnel_update(tunnel_id, name=None, description=None, organization_ids=None, workspace_ids=None) -> dict`.
- Adds `tunnel_delete(tunnel_id, confirm_tunnel_id) -> dict`.
- Adds `_resolve_scope(...) -> tuple[list[str], list[str]]` and `_normalize_tunnel(payload) -> dict`.

- [ ] **Step 1: Write failing tunnel normalization/scope tests**

Fake `tunnel-client admin tunnels get ... --json` with one existing EBRIDGE tunnel carrying one organization and one workspace. Assert `tunnel_create(..., inherit_scope_from_tunnel=<id>)` builds the create call with those exact attachments and never guesses ids.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `PYTHONPATH=. /opt/eiros-control-plane/venv/bin/python -m pytest -q runtime/test_openai_control_plane.py -k tunnel`

Expected: missing methods / assertion failures.

- [ ] **Step 3: Implement list/get/create/update with installed CLI-compatible command builders**

During implementation, inspect only `tunnel-client admin tunnels <verb> --help` to map actual flags. JSON responses are parsed and normalized to stable fields (`tunnel_id`, `name`, `description`, `organization_ids`, `workspace_ids`, `status`, `created_at`, `updated_at`, bounded `raw_meta`). All returned text is redacted.

- [ ] **Step 4: Write failing delete/protected-target tests**

Assert:
```python
with pytest.raises(ControlPlaneError) as exc:
    op.tunnel_delete(target, confirm_tunnel_id="different")
assert exc.value.category == "confirmation_mismatch"

with pytest.raises(ControlPlaneError) as exc:
    protected.tunnel_delete(ebridge_id, confirm_tunnel_id=ebridge_id)
assert exc.value.category == "protected_target"
```

- [ ] **Step 5: Implement guarded delete and audit mutation results**

Every create/update/delete writes one redacted audit event. Create/update require no confirmation. Delete requires same-id confirmation and refuses protected tunnel ids.

- [ ] **Step 6: Run Task 2 tests and commit**

Run: `PYTHONPATH=. /opt/eiros-control-plane/venv/bin/python -m pytest -q runtime/test_openai_control_plane.py`

Then:
```bash
git add runtime/openai_control_plane.py runtime/test_openai_control_plane.py
git commit -m "feat: manage OpenAI tunnels from VPS Ops"
```

---

### Task 3: Runtime, local profile, and tunnel-daemon lifecycle

**Files:**
- Modify: `runtime/openai_control_plane.py`
- Modify: `runtime/test_openai_control_plane.py`

**Interfaces:**
- Runtime: `runtime_list`, `runtime_get`, `runtime_create`, `runtime_update`, `runtime_delete`.
- Profile: `profile_list`, `profile_get`, `profile_create`, `profile_validate`, `profile_delete`.
- Daemon: `daemon_install`, `daemon_status`, `daemon_start`, `daemon_stop`, `daemon_restart`, `daemon_remove`.
- Generated service naming: `eiros-tunnel-<slug>.service`.

- [ ] **Step 1: Discover installed CLI contracts without mutation**

Run help-only commands for:
```text
tunnel-client runtimes --help
tunnel-client runtimes create --help
tunnel-client runtimes update --help
tunnel-client runtimes delete --help
tunnel-client profiles --help
tunnel-client init --help
tunnel-client doctor --help
```
Record exact installed flags in test fixtures/comments so wrappers are grounded in the VPS version.

- [ ] **Step 2: Write failing runtime/profile command-construction tests**

Use FakeRunner. Assert runtime creation maps alias/tunnel/url/scope to the installed CLI, profile creation maps to `tunnel-client init --profile <slug> --tunnel-id <id> --mcp-server-url <loopback-url>`, and profile reads redact any `api_key` values from returned YAML/text.

- [ ] **Step 3: Implement runtime/profile operations**

Runtime/profile delete uses same-target confirmation. Profile names in the protected set cannot be deleted. `profile_validate()` maps doctor failures to `doctor_failed` and returns bounded/redacted diagnostics.

- [ ] **Step 4: Write failing daemon lifecycle tests**

Assert generated unit content:
```ini
[Service]
User=eiros
Group=eiros
EnvironmentFile=/etc/eiros/tunnel.env
ExecStart=/usr/local/bin/tunnel-client run --profile rental-agent --health.listen-addr 127.0.0.1:0 --health.url-file /home/eiros/rental-agent-tunnel-health.url
Restart=always
RestartSec=3
```
Assert service/profile slug validation prevents path/service injection. Remove requires same-name confirmation and protected services cannot be removed.

- [ ] **Step 5: Implement daemon lifecycle**

Write units only under `/etc/systemd/system/eiros-tunnel-<slug>.service`; call `systemctl daemon-reload/enable/start/stop/restart/disable` with argv arrays. Return only service state and redacted journal/status snippets. Mutation is audited.

- [ ] **Step 6: Run Task 3 tests and commit**

Run: `PYTHONPATH=. /opt/eiros-control-plane/venv/bin/python -m pytest -q runtime/test_openai_control_plane.py`

Then:
```bash
git add runtime/openai_control_plane.py runtime/test_openai_control_plane.py
git commit -m "feat: manage OpenAI runtimes profiles and daemons"
```

---

### Task 4: One-shot provisioning and VPS Ops MCP tool surface

**Files:**
- Modify: `runtime/openai_control_plane.py`
- Modify: `runtime/vps_ops_server.py`
- Create: `runtime/test_vps_ops_openai_tools.py`
- Modify: `runtime/test_openai_control_plane.py`

**Interfaces:**
- Adds `connector_provision(alias, name, description, mcp_server_url, inherit_scope_from_tunnel="", organization_ids=None, workspace_ids=None) -> dict`.
- VPS Ops tools:
  - `openai_admin_status`
  - `openai_control_plane_audit`
  - `openai_tunnel_list`, `openai_tunnel_get`, `openai_tunnel_create`, `openai_tunnel_update`, `openai_tunnel_delete`
  - `openai_runtime_list`, `openai_runtime_get`, `openai_runtime_create`, `openai_runtime_update`, `openai_runtime_delete`
  - `openai_profile_list`, `openai_profile_get`, `openai_profile_create`, `openai_profile_validate`, `openai_profile_delete`
  - `openai_tunnel_daemon_install`, `openai_tunnel_daemon_status`, `openai_tunnel_daemon_start`, `openai_tunnel_daemon_stop`, `openai_tunnel_daemon_restart`, `openai_tunnel_daemon_remove`
  - `openai_connector_provision`

- [ ] **Step 1: Write failing idempotent provisioning tests**

Fake state starts empty. Assert provisioning calls create tunnel -> create profile/runtime as supported -> validate profile -> install/start daemon -> readiness. A second call with the same managed alias must return `reused`/`updated` rather than creating a duplicate tunnel.

- [ ] **Step 2: Implement `connector_provision()`**

Return:
```python
{
    "ok": True,
    "alias": "rental-agent",
    "tunnel": {"state": "created|reused|updated", "tunnel_id": "..."},
    "runtime": {"state": "created|reused|updated|not_required", ...},
    "profile": {"state": "created|reused|updated", "name": "rental-agent"},
    "daemon": {"state": "installed|running|restarted", "service": "eiros-tunnel-rental-agent.service"},
    "ready": True|False,
    "needs_user_action": "" | "chatgpt_connector_activation" | "scope" | "doctor_failed",
}
```

- [ ] **Step 3: Write failing MCP tool-registration contract test**

Import `runtime.vps_ops_server`, list tools through FastMCP, and assert all tools above exist. Wrapper tests monkeypatch the module-level operator and verify args are forwarded without changing semantics.

- [ ] **Step 4: Implement thin MCP wrappers in `runtime/vps_ops_server.py`**

Wrappers contain no tunnel-client subprocess logic. Update connector instructions to tell ChatGPT to prefer `openai_connector_provision` for new MCP connectors and lower-level `openai_*` tools for repair/inspection.

- [ ] **Step 5: Run all new tests + compile**

Run:
```bash
PYTHONPATH=. /opt/eiros-control-plane/venv/bin/python -m pytest -q runtime/test_openai_control_plane.py runtime/test_vps_ops_openai_tools.py
/opt/eiros-control-plane/venv/bin/python -m py_compile runtime/openai_control_plane.py runtime/vps_ops_server.py
```

Expected: PASS / exit 0.

- [ ] **Step 6: Commit Task 4**

```bash
git add runtime/openai_control_plane.py runtime/vps_ops_server.py runtime/test_openai_control_plane.py runtime/test_vps_ops_openai_tools.py
git commit -m "feat: expose OpenAI connector provisioning in VPS Ops"
```

---

### Task 5: Live smoke, Rental Agent tunnel provisioning, and regression verification

**Files:**
- Modify only Task 1–4 files if live defects are proven.
- Update spec only for verified installed-CLI contract corrections.

**Interfaces:**
- Live target MCP URL: `http://127.0.0.1:8794/mcp`.
- Managed alias: `rental-agent`.
- Intended production outcome: dedicated OpenAI tunnel/profile/daemon for Rental Agent; existing EBRIDGE tunnel remains untouched.

- [ ] **Step 1: Run full existing EIROS baseline tests in the isolated worktree**

Run every existing `runtime/test_*.py` self-test with `PYTHONPATH=.` plus the new pytest suite. Any pre-existing test incompatibility must be separated from a regression caused by this branch.

- [ ] **Step 2: Live-read admin/tunnel state through the helper**

Invoke `OpenAIControlPlane.admin_status()` and tunnel inventory/get using the active admin profile/secret reference. Verify returned JSON contains no secret-like values.

- [ ] **Step 3: Resolve EBRIDGE scope without modifying it**

Read the existing known-good EBRIDGE tunnel metadata and capture only its tunnel id plus organization/workspace attachment ids for inheritance. Mark that tunnel/profile/service protected in the live operator configuration.

- [ ] **Step 4: Provision Rental Agent live**

Call:
```python
operator.connector_provision(
    alias="rental-agent",
    name="EIROS Rental Agent",
    description="Dedicated EIROS rental discovery MCP connector",
    mcp_server_url="http://127.0.0.1:8794/mcp",
    inherit_scope_from_tunnel=<existing ebridge tunnel id>,
)
```

Expected: a new `tunnel_<32>` id, `rental-agent` profile, `eiros-tunnel-rental-agent.service`, and readiness/doctor output. Do not delete this tunnel: it is the production target.

- [ ] **Step 5: Verify EBRIDGE protection and Rental readiness**

Confirm existing EBRIDGE tunnel id is unchanged and reachable. Confirm Rental Agent tunnel metadata/get succeeds and its daemon is active. Confirm local Rental MCP still advertises the eight `rental_*` tools and `ui://eiros-rental/app-v1.html`.

- [ ] **Step 6: Fresh verification before completion**

Run:
```bash
PYTHONPATH=. /opt/eiros-control-plane/venv/bin/python -m pytest -q runtime/test_openai_control_plane.py runtime/test_vps_ops_openai_tools.py
/opt/eiros-control-plane/venv/bin/python -m py_compile runtime/openai_control_plane.py runtime/vps_ops_server.py
git status --short
git log --oneline -8
```

Only after this evidence may the branch be presented for integration.

---

## Self-Review Checklist

- Spec coverage: admin status, tunnel CRUD, runtime CRUD, profiles, daemons, one-shot provisioning, audit, protection, secret redaction, live Rental provisioning are each assigned to a task.
- Placeholder scan must return no forbidden planning markers.
- Stable interface names above must be used consistently by helper tests and MCP wrappers.
- Real OpenAI mutations are isolated to Task 5 after the fake-runner suite is green.
- Existing EBRIDGE tunnel deletion is impossible through v1 purpose-built tools.
