# Subscriber Identity Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reconcile the reviewed authentication/facade work with the device-bound public SubscriberNumber model without regressing signature, replay, revocation, scope, or connector-delegation security.

**Architecture:** Keep the existing transport-neutral PrincipalRegistry/AuthStore mechanics, but split callable subscriber semantics from non-dialable service principals. Preserve legacy `agent_number` as a migration field during this slice, add trusted `subscriber_number` to AuthContext, make public-number registration exclusive to one interactive installation, and hard-reject service contexts at subscriber-only collaboration mutations. Runtime sessions remain below the existing collab subscriber record and do not allocate another public number.

**Tech Stack:** Python 3, pytest, dataclasses, existing `runtime.agent_auth`, `runtime.collab`, and `runtime.authenticated_collab` facade.

**Spec:** `docs/superpowers/specs/2026-08-24-eiros-subscriber-identity-model.md`

## Global Constraints

- Public SubscriberNumber cardinality is one human/user context x platform x concrete device/installation.
- HEADLESS_SERVICE, WATCHDOG, SERVER_WORKER, and TRUSTED_CONNECTOR are non-dialable and may authenticate only without a public SubscriberNumber.
- Existing canonical signing, timestamp_ms, atomic replay consume, revocation, scopes, and payload/method binding behavior must remain green.
- Connector relay authority remains an explicit allowlist and must not widen beyond delegated subscriber numbers.
- `main` remains untouched; all work stays in `test/subscriber-identity-reconcile` until dual review.
- TDD: production behavior changes only after a failing test demonstrates the old-model defect.

---

### Task 1: Integrate the already-reviewed AuthenticatedCollab baseline

**Files:**
- Import reviewed history that creates/modifies `runtime/authenticated_collab.py` and its contract tests.

**Interfaces:**
- Consumes: approved pure-auth base `c0b38ab`.
- Produces: existing `_actor(auth, claimed_agent) -> str` facade baseline that currently returns `auth.agent_number`.

- [x] **Step 1:** Cherry-pick reviewed commits `3618b8c`, `ee5f3c8`, `011ecad` onto this reconcile branch.
- [x] **Step 2:** Run `/opt/eiros-control-plane/venv/bin/pytest -q runtime/test_authenticated_collab.py` and verify the imported baseline is green before new subscriber tests.
- [x] **Step 3:** Commit only if cherry-pick did not preserve the original commits automatically; otherwise proceed without an extra commit.

### Task 2: Lock the remaining subscriber RED/survivor contract

**Files:**
- Modify: `runtime/test_agent_auth.py`
- Modify: `runtime/test_authenticated_collab.py`
- Create: `runtime/test_subscriber_sessions.py`

**Interfaces:**
- Consumes: `PrincipalRegistry.register_principal`, `AuthContext`, `ConnectorBinding`, `collab.bootstrap_agent`, `collab.session_heartbeat`, `AuthenticatedCollab.send_message`.
- Produces: explicit contract coverage for spec section 8 items #2, #3, #6, #7.

- [x] **Step 1:** Add a parameterized test asserting each non-dialable PrincipalType raises `AuthError` when registered with a non-empty `SUB-*` public number. Current code must FAIL because registration is currently accepted.
- [x] **Step 2:** Add a facade test using a HEADLESS_SERVICE AuthContext and assert subscriber-only `send_message` raises `AuthError` before the engine is called. Current facade must FAIL by calling the engine with the service `agent_number`.
- [x] **Step 3:** Add an isolated-temp-store collab regression: bootstrap one platform+instance, record `phone_number`, heartbeat two distinct runtime session_ids, then re-bootstrap the same platform+instance and assert the same `agent_id` and same `phone_number`; assert two sessions are present. This is expected to PASS already and locks item #3 as a survivor.
- [x] **Step 4:** Add ConnectorBinding subscriber-named regression that allows delegated `SUB-A` and rejects undelegated `SUB-B`; expected to PASS already and locks item #7 as a survivor.
- [x] **Step 5:** Run only the new tests. Expected result: item #2 and #6 fail for intended old-model behavior; #3/#7 pass.

### Task 3: Minimal GREEN for subscriber/service identity split

**Files:**
- Modify: `runtime/agent_auth.py`
- Modify: `runtime/authenticated_collab.py`

**Interfaces:**
- Produces: `NonDialablePrincipalRegistration`, `SubscriberActorRequired`, `AuthContext.subscriber_number: str | None`.
- Preserves: legacy `AuthContext.agent_number` during migration.

- [x] **Step 1:** Add `NonDialablePrincipalRegistration(AuthError)` as a sibling policy error, not a re-registration-conflict subtype, and reject non-empty public-number registration for HEADLESS_SERVICE/WATCHDOG/SERVER_WORKER/TRUSTED_CONNECTOR before idempotent/rebind handling.
- [x] **Step 2:** Add a reverse-index exclusivity guard: a non-empty public number already owned by a different INTERACTIVE_INSTALLATION principal rejects the second registration with `ConflictingPrincipalRegistration`; exact same principal re-registration remains idempotent and revocation-safe.
- [x] **Step 3:** Add `subscriber_number: str | None` to AuthContext. AuthStore sets it to the registered public number only for INTERACTIVE_INSTALLATION; all service types receive `None`. Preserve `agent_number` as migration compatibility during this slice, but never infer subscriber authority automatically from that legacy field in `AuthContext.__post_init__`; directly constructed trusted test/adaptor contexts must set `subscriber_number` explicitly.
- [x] **Step 4:** Add `SubscriberActorRequired(AuthError)` and change `AuthenticatedCollab._actor()` to reject any context without a callable subscriber actor before invoking the engine. Body identity remains assertion-only and validated against the trusted subscriber actor.
- [x] **Step 5:** Run the new RED tests; all must pass.
- [x] **Step 6:** Run `runtime/test_agent_auth.py` and `runtime/test_authenticated_collab.py`; all old security regressions must remain green.

### Task 4: Full verification, migration note, and independent review

**Files:**
- Modify: `docs/superpowers/specs/2026-08-24-eiros-subscriber-identity-model.md` only if needed to clarify migration status/evidence wording.

**Interfaces:**
- Produces: one reviewable SHA for Claude; no production activation.

- [x] **Step 1:** Run `/opt/eiros-control-plane/venv/bin/python -m py_compile runtime/agent_auth.py runtime/authenticated_collab.py`.
- [x] **Step 2:** Run `/opt/eiros-control-plane/venv/bin/pytest -q` and record exact totals.
- [x] **Step 3:** Run `git diff --check` and inspect `git status --short`.
- [x] **Step 4:** Commit the reconcile slice with a focused message and push `test/subscriber-identity-reconcile`.
- [x] **Step 5:** Send exact SHA + test evidence + known migration caveat (`agent_number`/`phone_number` names remain legacy adapters) to Claude for independent review. Review request is durable in EIROS Room; do not merge to main until review returns GREEN.
