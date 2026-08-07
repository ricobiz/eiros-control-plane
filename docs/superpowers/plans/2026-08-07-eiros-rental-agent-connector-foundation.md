# EIROS Rental Agent Connector Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and deploy a dedicated EIROS Rental Agent MCP connector with its own process, durable SQLite store, MCP tools, in-chat MCP App card, and independent OpenAI Secure MCP tunnel profile.

**Architecture:** The Rental Agent is a separate FastMCP server, not a tool bundle inside EBRIDGE. Internally it is a modular monolith under `runtime/rental_agent/`; ChatGPT talks to the dedicated connector, while EBRIDGE remains the infrastructure/admin bridge. Foundation v1 stops at durable property ingest/query/status and the in-chat UI; autonomous Scout and live messaging adapters are added in later plans on top of these interfaces.

**Tech Stack:** Python 3.12, FastMCP, Starlette, SQLite (`sqlite3`), pytest, systemd, OpenAI `tunnel-client`, MCP Apps `ui://` resources.

## Global Constraints

- Dedicated Rental Agent MCP connector and dedicated systemd service; do not register rental tools in `runtime/server_v2.py`.
- Dedicated OpenAI Secure MCP tunnel profile/daemon for Rental Agent; EBRIDGE tunnel remains untouched.
- Daily operator surface is ChatGPT; no external dashboard is required.
- MCP App UI renders directly in ChatGPT from a `ui://` resource.
- Durable primary store is SQLite on the VPS.
- Current authority is market discovery only: no negotiation, viewing scheduling, commitments, deposits, payments, or contracts.
- No personal/business/company/payment/move-date background is volunteered by the system.
- Session secrets/tokens must never be returned by ordinary MCP tools or committed to git.
- Existing dirty/uncommitted EIROS work must not be staged or modified unless explicitly named in a task below.

---

## File Structure

Create a focused package rather than one giant server file:

- `runtime/rental_agent/__init__.py` — package marker and version.
- `runtime/rental_agent/config.py` — paths, port, connector/tunnel defaults; no secrets.
- `runtime/rental_agent/models.py` — typed dataclasses/enums shared by DB/service/server.
- `runtime/rental_agent/db.py` — SQLite connection, migrations, CRUD primitives.
- `runtime/rental_agent/policy.py` — current authority gate and disclosure policy.
- `runtime/rental_agent/service.py` — domain operations used by MCP tools.
- `runtime/rental_agent/server.py` — dedicated FastMCP/Starlette connector and MCP App resources only.
- `runtime/rental_agent/ui/app.html` — Rental Agent in-chat MCP App card.
- `runtime/rental_agent/tunnel.py` — safe tunnel profile/bootstrap helper; never handles raw keys in responses/logs.
- `runtime/rental_agent/tests/test_db.py` — schema/CRUD tests.
- `runtime/rental_agent/tests/test_policy.py` — authority gate tests.
- `runtime/rental_agent/tests/test_service.py` — ingest/status/shortlist tests.
- `runtime/rental_agent/tests/test_server_contract.py` — tool/resource registration contract.
- `runtime/rental_agent/tests/test_tunnel.py` — profile rendering and secret-redaction tests.
- `deploy/eiros-rental-mcp.service` — dedicated connector service.
- `deploy/eiros-rental-tunnel.service` — dedicated tunnel-client service.
- `deploy/rental-tunnel-profile.example.yaml` — non-secret profile template/reference.
- `deploy/install_rental_agent.py` — idempotent installer for directories, service files, DB bootstrap, tunnel profile creation when a tunnel id is supplied.

Runtime state:

- `/var/lib/eiros-rental/rental.db`
- `/var/lib/eiros-rental/browser/` (created now, used by later Scout/messaging plans)
- `/var/lib/eiros-rental/logs/`
- `/etc/eiros/rental-agent.env` (root-readable service environment, no repo copy)
- Tunnel profile `rental-agent`, created by running `tunnel-client init --profile rental-agent ...` as OS user `eiros`; the CLI owns the canonical profile path.

---

### Task 1: Durable database and shared models

**Files:**
- Create: `runtime/rental_agent/__init__.py`
- Create: `runtime/rental_agent/config.py`
- Create: `runtime/rental_agent/models.py`
- Create: `runtime/rental_agent/db.py`
- Test: `runtime/rental_agent/tests/test_db.py`

**Interfaces:**
- Produces: `RentalDatabase(path: Path)`, `RentalDatabase.initialize()`, `RentalDatabase.health()`, `RentalDatabase.create_lead(...)`, `RentalDatabase.get_property(...)`, `RentalDatabase.list_properties(...)`.
- Produces: `LeadInput`, `PropertyRecord`, `AuthorityAction`, `ActionDecision` dataclasses/enums used later.

- [ ] **Step 1: Write the failing database test**

Create `runtime/rental_agent/tests/test_db.py` with tests that instantiate a temporary SQLite file, call `initialize()`, assert `PRAGMA user_version == 1`, insert one raw lead with source kind `text`, and retrieve one canonical property record.

```python
from pathlib import Path

from runtime.rental_agent.db import RentalDatabase
from runtime.rental_agent.models import LeadInput


def test_initialize_and_ingest_text_lead(tmp_path: Path) -> None:
    db = RentalDatabase(tmp_path / "rental.db")
    db.initialize()
    assert db.health()["schema_version"] == 1

    result = db.create_lead(
        LeadInput(
            source_kind="text",
            source_value="Sunset Town whole shophouse 5 floors 25m VND/month",
            context={"origin": "test"},
        )
    )
    record = db.get_property(result.property_id)
    assert record is not None
    assert record.property_id == result.property_id
    assert record.status == "new"
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `pytest -q runtime/rental_agent/tests/test_db.py`

Expected: import/module failure because the package does not exist yet.

- [ ] **Step 3: Implement models and schema**

Implement migration version 1 with tables needed by the foundation and stable IDs generated in Python:

```sql
CREATE TABLE properties (
  property_id TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  project_name TEXT NOT NULL DEFAULT '',
  locality TEXT NOT NULL DEFAULT '',
  monthly_rent_vnd INTEGER,
  floors INTEGER,
  area_m2 REAL,
  lease_min_months INTEGER,
  deposit_months REAL,
  fit_score REAL NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE TABLE listing_sources (
  source_id TEXT PRIMARY KEY,
  property_id TEXT NOT NULL REFERENCES properties(property_id),
  source_kind TEXT NOT NULL,
  source_value TEXT NOT NULL,
  source_url TEXT NOT NULL DEFAULT '',
  raw_json TEXT NOT NULL DEFAULT '{}',
  captured_at INTEGER NOT NULL,
  UNIQUE(source_kind, source_value)
);
CREATE TABLE contacts (
  contact_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  value_normalized TEXT NOT NULL,
  display_value TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  UNIQUE(kind, value_normalized)
);
CREATE TABLE property_contacts (
  property_id TEXT NOT NULL REFERENCES properties(property_id),
  contact_id TEXT NOT NULL REFERENCES contacts(contact_id),
  provenance_source_id TEXT,
  PRIMARY KEY(property_id, contact_id)
);
CREATE TABLE audit_events (
  event_id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL,
  property_id TEXT,
  payload_json TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
```

`create_lead()` must be idempotent for the same `(source_kind, source_value)` and must never duplicate a source row on retry.

- [ ] **Step 4: Run DB tests**

Run: `pytest -q runtime/rental_agent/tests/test_db.py`

Expected: PASS.

- [ ] **Step 5: Commit only Task 1 files**

```bash
git add runtime/rental_agent/__init__.py runtime/rental_agent/config.py runtime/rental_agent/models.py runtime/rental_agent/db.py runtime/rental_agent/tests/test_db.py
git commit -m "feat: add rental agent durable store"
```

---

### Task 2: Authority policy and domain service

**Files:**
- Create: `runtime/rental_agent/policy.py`
- Create: `runtime/rental_agent/service.py`
- Test: `runtime/rental_agent/tests/test_policy.py`
- Test: `runtime/rental_agent/tests/test_service.py`

**Interfaces:**
- Consumes: `RentalDatabase`, `LeadInput`, `AuthorityAction`, `ActionDecision`.
- Produces: `RentalPolicy.current() -> dict`, `RentalPolicy.check(action: AuthorityAction) -> ActionDecision`.
- Produces: `RentalService.status()`, `ingest_text()`, `ingest_url()`, `ingest_phone()`, `property()`, `shortlist()`, `policy()`.

- [ ] **Step 1: Write failing policy tests**

```python
from runtime.rental_agent.models import AuthorityAction
from runtime.rental_agent.policy import RentalPolicy


def test_market_discovery_policy_allows_contact_but_blocks_negotiation() -> None:
    policy = RentalPolicy()
    assert policy.check(AuthorityAction.CONTACT_DISCOVERY).allowed is True
    assert policy.check(AuthorityAction.NEGOTIATE).allowed is False
    assert policy.check(AuthorityAction.SCHEDULE_VIEWING).allowed is False
    assert policy.check(AuthorityAction.SEND_MONEY).allowed is False
```

- [ ] **Step 2: Run policy tests and verify failure**

Run: `pytest -q runtime/rental_agent/tests/test_policy.py`

Expected: FAIL because `RentalPolicy` is not implemented.

- [ ] **Step 3: Implement policy with explicit allow/deny map**

`AuthorityAction` values for foundation must include exactly:

```python
SEARCH = "search"
INGEST = "ingest"
CONTACT_DISCOVERY = "contact_discovery"
REQUEST_MEDIA = "request_media"
COMPARE_RANK = "compare_rank"
NEGOTIATE = "negotiate"
SCHEDULE_VIEWING = "schedule_viewing"
BINDING_COMMITMENT = "binding_commitment"
AGREE_DEPOSIT = "agree_deposit"
SEND_MONEY = "send_money"
CONTRACT = "contract"
```

Allowed in current mode: SEARCH, INGEST, CONTACT_DISCOVERY, REQUEST_MEDIA, COMPARE_RANK. All others return `allowed=False`, `reason="blocked_by_market_discovery_policy"`.

- [ ] **Step 4: Write and run failing service tests**

Test that `RentalService.ingest_url("https://example.com/listing/1")` creates a retrievable property/source; `status()` reports DB schema/version and policy mode `market_discovery_only`; `shortlist(limit=10)` returns stable JSON-serializable rows ordered by fit score then freshness.

Run: `pytest -q runtime/rental_agent/tests/test_service.py`

Expected: FAIL until service exists.

- [ ] **Step 5: Implement minimal service and pass tests**

The service does not fetch the URL yet; it records the lead and provenance. Scout fetching belongs to the later Scout plan.

Run: `pytest -q runtime/rental_agent/tests/test_policy.py runtime/rental_agent/tests/test_service.py`

Expected: PASS.

- [ ] **Step 6: Commit Task 2 files**

```bash
git add runtime/rental_agent/policy.py runtime/rental_agent/service.py runtime/rental_agent/models.py runtime/rental_agent/tests/test_policy.py runtime/rental_agent/tests/test_service.py
git commit -m "feat: add rental agent policy and service"
```

---

### Task 3: Dedicated FastMCP server and MCP tool contract

**Files:**
- Create: `runtime/rental_agent/server.py`
- Create: `runtime/rental_agent/tests/test_server_contract.py`
- Modify: `requirements.txt` only if an already-installed imported package is missing from the declared dependencies.

**Interfaces:**
- Consumes: `RentalService`.
- Produces MCP tools: `rental_status`, `rental_ingest_text`, `rental_ingest_url`, `rental_ingest_phone`, `rental_property`, `rental_shortlist`, `rental_policy`, `rental_open_app`.
- Runs stateless Streamable HTTP on `127.0.0.1:8794`.

- [ ] **Step 1: Write a failing server contract test**

Import `runtime.rental_agent.server` and assert the expected tool/resource names are registered or exposed by a small testable registry helper in the module.

Expected tool set:

```python
{
    "rental_status",
    "rental_ingest_text",
    "rental_ingest_url",
    "rental_ingest_phone",
    "rental_property",
    "rental_shortlist",
    "rental_policy",
    "rental_open_app",
}
```

Expected UI resource URI prefix: `ui://eiros-rental/`.

- [ ] **Step 2: Run contract test and verify failure**

Run: `pytest -q runtime/rental_agent/tests/test_server_contract.py`

Expected: FAIL because server module does not exist.

- [ ] **Step 3: Implement dedicated FastMCP server**

Use the proven `runtime/mastering_mcp_server.py` structure without importing or mutating EBRIDGE's main `mcp` object:

```python
mcp = FastMCP(
    "EIROS Rental Agent",
    instructions="Dedicated rental discovery connector for Rico ...",
    stateless_http=True,
    json_response=True,
    host="127.0.0.1",
    port=8794,
    transport_security=TransportSecuritySettings(...),
)
```

Server startup initializes `/var/lib/eiros-rental/rental.db` or `EIROS_RENTAL_DATA_DIR/rental.db` for tests/development. Tool responses return structured JSON only and never filesystem secrets.

- [ ] **Step 4: Run contract plus service tests**

Run: `pytest -q runtime/rental_agent/tests/test_server_contract.py runtime/rental_agent/tests/test_service.py runtime/rental_agent/tests/test_policy.py runtime/rental_agent/tests/test_db.py`

Expected: PASS.

- [ ] **Step 5: Compile server**

Run: `python -m py_compile runtime/rental_agent/server.py runtime/rental_agent/service.py runtime/rental_agent/db.py`

Expected: exit 0.

- [ ] **Step 6: Commit Task 3 files**

```bash
git add runtime/rental_agent/server.py runtime/rental_agent/tests/test_server_contract.py requirements.txt
git commit -m "feat: expose dedicated rental MCP tools"
```

---

### Task 4: MCP App card rendered inside ChatGPT

**Files:**
- Create: `runtime/rental_agent/ui/app.html`
- Modify: `runtime/rental_agent/server.py`
- Modify: `runtime/rental_agent/tests/test_server_contract.py`

**Interfaces:**
- Produces resource: `ui://eiros-rental/app-v1.html`.
- `rental_open_app()` returns the MCP App resource metadata so ChatGPT mounts the card.
- UI calls only Rental Agent MCP tools through the MCP Apps bridge.

- [ ] **Step 1: Extend failing contract test for UI metadata**

Assert the resource metadata contains:

```python
{
    "ui": {"prefersBorder": True, "csp": {"connectDomains": [], "resourceDomains": []}},
    "openai/widgetDescription": "EIROS Rental Agent — shortlist, properties and discovery status.",
}
```

Custom widget origin is not required for v1 because the UI uses the managed ChatGPT sandbox and no external assets.

- [ ] **Step 2: Run contract test and verify failure**

Run: `pytest -q runtime/rental_agent/tests/test_server_contract.py`

Expected: FAIL for missing UI resource/metadata.

- [ ] **Step 3: Implement compact in-chat card**

The first-frame UI must contain:
- connector health/state
- active search profile summary
- counts: properties / qualified / contacted / needs action
- shortlist table/cards with property id, project/locality, rent, floors, fit score, status
- refresh button calling `rental_status` + `rental_shortlist`
- text/URL/phone ingest controls calling the corresponding tools
- no external website link required for normal operation

The card may expose an `AUTH NEEDED` badge later, but channel login UI is implemented in the messaging plan rather than faked now.

- [ ] **Step 4: Run tests and compile server**

Run: `pytest -q runtime/rental_agent/tests/test_server_contract.py && python -m py_compile runtime/rental_agent/server.py`

Expected: PASS / exit 0.

- [ ] **Step 5: Commit Task 4 files**

```bash
git add runtime/rental_agent/ui/app.html runtime/rental_agent/server.py runtime/rental_agent/tests/test_server_contract.py
git commit -m "feat: add rental agent in-chat app"
```

---

### Task 5: Dedicated systemd deployment

**Files:**
- Create: `deploy/eiros-rental-mcp.service`
- Create: `deploy/install_rental_agent.py`
- Test: add installer dry-run assertions in `runtime/rental_agent/tests/test_server_contract.py` or create `runtime/rental_agent/tests/test_install.py` if cleaner.

**Interfaces:**
- Service name: `eiros-rental-mcp.service`.
- Working directory: `/opt/eiros-control-plane`.
- Exec: `/opt/eiros-control-plane/venv/bin/python -m runtime.rental_agent.server`.
- State directory: `/var/lib/eiros-rental` owned by dedicated OS user `eiros-rental` when available; installer creates it.

- [ ] **Step 1: Write failing installer/service assertions**

Assert the checked-in unit contains `User=eiros-rental`, `ExecStart=/opt/eiros-control-plane/venv/bin/python -m runtime.rental_agent.server`, `Restart=always`, and an environment file path `/etc/eiros/rental-agent.env`.

- [ ] **Step 2: Run test and verify failure**

Run: `pytest -q runtime/rental_agent/tests/test_install.py`

Expected: FAIL until files exist.

- [ ] **Step 3: Implement unit and idempotent installer**

Installer actions:
1. create `eiros-rental` system user if absent;
2. create `/var/lib/eiros-rental/{browser,logs}` with restrictive ownership;
3. create `/etc/eiros/rental-agent.env` containing only non-secret defaults if absent (`EIROS_RENTAL_DATA_DIR=/var/lib/eiros-rental`, `EIROS_RENTAL_PORT=8794`);
4. install/copy the unit to `/etc/systemd/system/eiros-rental-mcp.service`;
5. `daemon-reload`, enable and start/restart service;
6. initialize database as `eiros-rental`;
7. print redacted health status only.

- [ ] **Step 4: Run unit tests then installer in dry-run mode**

Run: `pytest -q runtime/rental_agent/tests/test_install.py`

Then: `python deploy/install_rental_agent.py --dry-run`

Expected: PASS and a deterministic action list; no mutation in dry-run.

- [ ] **Step 5: Commit Task 5 files**

```bash
git add deploy/eiros-rental-mcp.service deploy/install_rental_agent.py runtime/rental_agent/tests/test_install.py
git commit -m "feat: deploy rental MCP service"
```

---

### Task 6: Independent OpenAI Secure MCP tunnel

**Files:**
- Create: `runtime/rental_agent/tunnel.py`
- Create: `runtime/rental_agent/tests/test_tunnel.py`
- Create: `deploy/eiros-rental-tunnel.service`
- Create: `deploy/rental-tunnel-profile.example.yaml`
- Modify: `deploy/install_rental_agent.py`

**Interfaces:**
- Tunnel profile name: `rental-agent`.
- Tunnel command target: local Streamable HTTP server URL `http://127.0.0.1:8794/mcp`, configured with the installed tunnel-client's verified `--mcp-server-url` option.
- Tunnel service: `eiros-rental-tunnel.service`.
- No tunnel id/admin/runtime key is ever printed by Rental Agent tools or installer logs.

- [ ] **Step 1: Write tunnel profile/redaction tests**

Test that `render_profile(tunnel_id="tun_test", api_key_ref="env:CONTROL_PLANE_API_KEY")` contains the reference but never a raw key value, and that status serialization emits only booleans such as `runtime_key_configured` / `tunnel_id_configured`.

- [ ] **Step 2: Run tunnel tests and verify failure**

Run: `pytest -q runtime/rental_agent/tests/test_tunnel.py`

Expected: FAIL until `tunnel.py` exists.

- [ ] **Step 3: Implement tunnel profile helper and service**

Use installed `tunnel-client` commands already verified on this VPS:

```text
tunnel-client init --profile rental-agent --tunnel-id <id> --mcp-server-url http://127.0.0.1:8794/mcp
tunnel-client doctor --profile rental-agent
tunnel-client run --profile rental-agent
```

The installer accepts `--tunnel-id` or reads `EIROS_RENTAL_TUNNEL_ID`; it does not create or delete OpenAI control-plane tunnel metadata automatically unless a later explicitly authorized operator action supplies an admin key. If no tunnel id is configured, foundation service remains healthy locally and reports `needs_user_action: tunnel_id` rather than guessing credentials.

- [ ] **Step 4: Run tunnel tests**

Run: `pytest -q runtime/rental_agent/tests/test_tunnel.py`

Expected: PASS.

- [ ] **Step 5: Commit Task 6 files**

```bash
git add runtime/rental_agent/tunnel.py runtime/rental_agent/tests/test_tunnel.py deploy/eiros-rental-tunnel.service deploy/rental-tunnel-profile.example.yaml deploy/install_rental_agent.py
git commit -m "feat: add independent rental MCP tunnel"
```

---

### Task 7: Deploy foundation and perform end-to-end smoke verification

**Files:**
- Modify only when a verified deployment defect is found in files created by Tasks 1–6.
- Update: `docs/superpowers/specs/2026-08-07-eiros-rental-agent-mcp-design.md` only if deployment reveals a real contract correction.

**Interfaces:**
- Foundation success is local service + independent tunnel readiness + ChatGPT connector-visible MCP tool/resource catalog.

- [ ] **Step 1: Run the full Rental Agent test suite**

Run:

```bash
pytest -q runtime/rental_agent/tests
python -m py_compile runtime/rental_agent/*.py
```

Expected: all tests PASS, compile exit 0.

- [ ] **Step 2: Install and start the local connector service**

Run:

```bash
python deploy/install_rental_agent.py
systemctl status eiros-rental-mcp.service --no-pager
```

Use the actual unit spelling `eiros-rental-mcp.service`; the command above must be corrected to that exact spelling before execution if copied from a client that visually substitutes characters.

Expected: `active (running)`.

- [ ] **Step 3: Probe local MCP endpoint**

Use `curl` only for HTTP readiness/headers; use MCP client/tool discovery for protocol verification. Confirm port 8794 is listening on loopback only and that tool/resource discovery includes the eight foundation tools plus `ui://eiros-rental/app-v1.html`.

- [ ] **Step 4: Provision/validate the independent tunnel profile**

If `EIROS_RENTAL_TUNNEL_ID` is configured, run installer tunnel step, `tunnel-client doctor --profile rental-agent`, enable/start `eiros-rental-tunnel.service`, and verify its `/readyz`/control-plane readiness through `tunnel-client health`.

If no tunnel id is configured, record exactly one `needs_user_action: tunnel_id` checkpoint. Do not alter the existing EBRIDGE tunnel and do not fabricate a tunnel id.

- [ ] **Step 5: Connect/reconnect the new Rental Agent connector in ChatGPT and verify the in-chat app**

Once the independent tunnel appears in ChatGPT connector settings, connect it, call `rental_status`, then `rental_open_app`. Verify the card renders inside this chat and refreshing it calls only the Rental Agent connector.

- [ ] **Step 6: Smoke ingest a non-production sample**

Call `rental_ingest_text` with a synthetic Sunset Town property, confirm `rental_shortlist` returns it, open the app and confirm the same canonical property id appears. Delete/reset only through an explicit foundation admin/reset helper if one has been added and tested; otherwise leave the synthetic record clearly marked `origin=test` and exclude it from production shortlist by default.

- [ ] **Step 7: Commit any verified deployment fixes**

If no fixes were needed, make no empty commit. If fixes were needed, stage only Rental Agent files and use:

```bash
git commit -m "fix: stabilize rental connector deployment"
```

---

## Follow-on Plans After Foundation

These are separate implementation plans because each is an independently testable subsystem:

1. **Scout + normalization + dedup + ranking** — autonomous web discovery and source adapters.
2. **Browser/session runtime + channel authentication** — persistent Playwright profiles and QR/OTP handoff.
3. **Zalo/WhatsApp/Telegram adapters + conversation ledger** — read/send synchronization using authenticated user sessions.
4. **Qualified outreach + reply parser + market discovery loop** — fit threshold, bounded first-contact messages, reply extraction, owner/agent consistency scoring, and end-to-end Phu Quoc verification.

The foundation interfaces above are the stable dependency surface for all four plans.
