# Subscriber Identity Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the old heterogeneous `agent_number -> set[principal]` public identity model with one device-bound callable SubscriberNumber per interactive installation while preserving the already-reviewed authentication primitives and current collaboration engine compatibility.

**Architecture:** `PrincipalRegistry` remains the credential/revocation source of truth but distinguishes dialable interactive principals from non-dialable ServicePrincipals. `AuthContext` exposes a trusted optional `subscriber_number`; subscriber-only collaboration rejects service contexts before engine invocation. During migration, the current collab engine remains the internal addressing substrate: authenticated Subscriber routing is resolved server-side into the existing collab record/`agent_id`, and legacy sequential `phone_number` values are never treated as final authentication identities.

**Tech Stack:** Python 3.12, pytest, existing `runtime.agent_auth`, `runtime.authenticated_collab`, `runtime.collab`.

**Spec:** `docs/superpowers/specs/2026-08-24-eiros-subscriber-identity-model.md`

## Global Constraints

- One public SubscriberNumber identifies one human/user-context × platform × concrete installation.
- HEADLESS_SERVICE, WATCHDOG, SERVER_WORKER and TRUSTED_CONNECTOR are non-dialable and have no public SubscriberNumber.
- Runtime sessions remain below a Subscriber and never allocate a second public number.
- Public-number knowledge never authenticates; trusted actor identity comes from verified server-side registry state.
- Existing canonical signing, method+payload binding, integer `timestamp_ms`, atomic replay consume, revocation, scopes and bearer/signed adapters must remain behaviorally unchanged.
- ServicePrincipal collaboration mutations hard-reject unless a future explicit delegation adapter produces subscriber authorization; there is no fallback from a missing subscriber actor to a service identity.
- Current sequential `phone_number` values are migration-only metadata, not final SubscriberNumbers.
- Main/prod stays untouched until the cumulative RED contract and GREEN implementation are independently reviewed.

---

### Task 1: Enforce dialable registration policy and one-to-one public number ownership

**Files:**
- Modify: `runtime/agent_auth.py` (`AuthError` subclasses and `PrincipalRegistry.register_principal`)
- Test: `runtime/test_agent_auth.py`

**Interfaces:**
- Consumes: existing `PrincipalType`, `ConflictingPrincipalRegistration`, `_by_agent_number` reverse index.
- Produces: `NonDialablePrincipalRegistration(AuthError)`; `register_principal(...)` allows a non-empty public number only for `INTERACTIVE_INSTALLATION`, and rejects a different interactive `principal_id` already bound to that number.

- [ ] **Step 1: Run the existing REDs and confirm the intended failures**

Run:
```bash
/opt/eiros-control-plane/venv/bin/pytest -q runtime/test_agent_auth.py -k 'non_dialable_principal_types or second_independent_installation'
```
Expected: 5 failures: four `DID NOT RAISE AuthError` service-policy failures and one `DID NOT RAISE ConflictingPrincipalRegistration` duplicate-installation failure.

- [ ] **Step 2: Add the distinct service-policy error**

Add beside the existing registration integrity error:
```python
class NonDialablePrincipalRegistration(AuthError):
    """A ServicePrincipal attempted to acquire a public SubscriberNumber."""
```

Do not subclass `ConflictingPrincipalRegistration`: source grep shows no production caller relies on that catch hierarchy, and policy ineligibility is not a re-registration conflict.

- [ ] **Step 3: Add the minimum registration guards before mutating registry state**

In `PrincipalRegistry.register_principal`, after exact same-`principal_id` idempotency/conflict handling and before assigning `_principals[principal_id]`:
```python
if principal_type is not PrincipalType.INTERACTIVE_INSTALLATION and agent_number:
    raise NonDialablePrincipalRegistration(
        f"principal type {principal_type.value!r} cannot own public subscriber number {agent_number!r}"
    )

if principal_type is PrincipalType.INTERACTIVE_INSTALLATION and agent_number:
    existing_members = self._by_agent_number.get(agent_number, set())
    if existing_members and principal_id not in existing_members:
        raise ConflictingPrincipalRegistration(
            f"public subscriber number {agent_number!r} is already bound to another installation"
        )
```

Keep empty-string legacy service registration working in this slice so existing internal service authentication can migrate without inventing a public number.

- [ ] **Step 4: Run the registration-policy tests**

Run:
```bash
/opt/eiros-control-plane/venv/bin/pytest -q runtime/test_agent_auth.py -k 'non_dialable_principal_types or second_independent_installation or re_registering_same_principal_id'
```
Expected: all selected tests PASS; exact repeat registration still preserves revocation epoch and conflicting same-principal credential rebinding still rejects.

- [ ] **Step 5: Commit Task 1**

```bash
git add runtime/agent_auth.py runtime/test_agent_auth.py
git commit -m "fix(auth): enforce subscriber registration cardinality"
```

---

### Task 2: Split authenticated principal identity from callable subscriber actor

**Files:**
- Modify: `runtime/agent_auth.py` (`AuthContext`, bearer verification, signed verification, identity assertion helper)
- Test: `runtime/test_agent_auth.py`

**Interfaces:**
- Consumes: `PrincipalRegistry.principal_type_for()` and `agent_number_for()`.
- Produces: `AuthContext.subscriber_number: str | None`; interactive verification returns the trusted registered number, service verification returns `None`.

- [ ] **Step 1: Re-run the current AuthContext RED**

Run:
```bash
/opt/eiros-control-plane/venv/bin/pytest -q runtime/test_agent_auth.py::test_service_auth_context_has_no_public_subscriber_number
```
Expected: FAIL with `AttributeError: 'AuthContext' object has no attribute 'subscriber_number'`.

- [ ] **Step 2: Add the optional trusted subscriber field**

Extend the frozen dataclass without removing legacy `agent_number` yet:
```python
@dataclasses.dataclass(frozen=True)
class AuthContext:
    principal_id: str
    agent_number: str
    principal_type: "PrincipalType"
    revocation_epoch: int
    authenticated_at: float
    scopes: "frozenset[str]" = frozenset()
    auth_method: str = ""
    subscriber_number: str | None = None
```

Keeping `agent_number` for the migration window avoids a repo-wide flag-day; authority decisions in new subscriber-only paths must use `subscriber_number`.

- [ ] **Step 3: Populate `subscriber_number` from trusted registry state in both verification paths**

For bearer verification:
```python
principal_type = self._registry.principal_type_for(bearer.principal_id)
registered_number = self._registry.agent_number_for(bearer.principal_id)
subscriber_number = (
    registered_number
    if principal_type is PrincipalType.INTERACTIVE_INSTALLATION
    else None
)
```
Use those values when constructing `AuthContext`.

For signed verification, after the existing signed claim membership/revocation checks:
```python
principal_type = self._registry.principal_type_for(principal_id)
subscriber_number = (
    agent_number_claim
    if principal_type is PrincipalType.INTERACTIVE_INSTALLATION
    else None
)
```
Do not alter signature, replay, skew, revocation or scope ordering.

- [ ] **Step 4: Make identity assertions compare against the callable subscriber when present**

Change `require_identity_match` to select the trusted subscriber actor first:
```python
expected = auth_context.subscriber_number
if expected is None:
    expected = auth_context.agent_number
if claimed_agent_id != expected:
    raise IdentityMismatch(...)
```

This preserves the old assertion helper for non-subscriber internal callers during migration. Subscriber-only facades add their own hard service rejection in Task 3, so this helper must not itself grant service collaboration authority.

- [ ] **Step 5: Run the entire auth contract**

Run:
```bash
/opt/eiros-control-plane/venv/bin/pytest -q runtime/test_agent_auth.py
```
Expected: all tests PASS, including cross-subscriber substitution, replay, revocation, scopes, payload/method binding and timestamp boundaries.

- [ ] **Step 6: Commit Task 2**

```bash
git add runtime/agent_auth.py runtime/test_agent_auth.py
git commit -m "fix(auth): expose trusted subscriber actor in auth context"
```

---

### Task 3: Hard-stop ServicePrincipals at subscriber-only collaboration boundaries

**Files:**
- Modify: `runtime/agent_auth.py` (new boundary error)
- Modify: `runtime/authenticated_collab.py`
- Test: `runtime/test_authenticated_collab.py`

**Interfaces:**
- Consumes: `AuthContext.subscriber_number` from Task 2.
- Produces: `SubscriberActorRequired(AuthError)`; `AuthenticatedCollab._actor()` returns only an authenticated SubscriberNumber and never falls back to a ServicePrincipal identity.

- [ ] **Step 1: Re-run the facade RED**

Run:
```bash
/opt/eiros-control-plane/venv/bin/pytest -q runtime/test_authenticated_collab.py::test_service_principal_is_rejected_before_subscriber_only_mutation
```
Expected: FAIL with `DID NOT RAISE AuthError`; current `_actor()` reaches the engine using an empty service `agent_number`.

- [ ] **Step 2: Add a specific subscriber-boundary error**

In `runtime/agent_auth.py`:
```python
class SubscriberActorRequired(AuthError):
    """The authenticated principal has no callable subscriber actor for this mutation."""
```

- [ ] **Step 3: Make `_actor()` require a subscriber before validating body assertions**

Update imports and implementation:
```python
from runtime.agent_auth import (
    AuthContext,
    SubscriberActorRequired,
    require_identity_match,
)

@staticmethod
def _actor(auth: AuthContext, claimed_agent: str | None) -> str:
    subscriber = auth.subscriber_number
    if subscriber is None:
        raise SubscriberActorRequired(
            f"principal {auth.principal_id!r} is not a callable subscriber"
        )
    if claimed_agent is not None:
        require_identity_match(claimed_agent, auth)
    return subscriber
```

There is deliberately no `or auth.agent_number` fallback here. A later connector delegation adapter must produce an explicitly subscriber-authorized context instead of masquerading the connector as the subscriber.

- [ ] **Step 4: Update existing facade fixtures to represent subscriber actors explicitly**

For every interactive `AuthContext` constructed directly in `runtime/test_authenticated_collab.py`, add the matching trusted subscriber number, e.g.:
```python
subscriber_number="chatgpt"
```
or
```python
subscriber_number="claude"
```
Keep the existing forged-body assertions unchanged so the old boundary security invariant remains covered.

- [ ] **Step 5: Run the facade contract**

Run:
```bash
/opt/eiros-control-plane/venv/bin/pytest -q runtime/test_authenticated_collab.py
```
Expected: all tests PASS and the service-principal test proves the engine function was never invoked.

- [ ] **Step 6: Commit Task 3**

```bash
git add runtime/agent_auth.py runtime/authenticated_collab.py runtime/test_authenticated_collab.py
git commit -m "fix(auth): require subscriber actor for collab mutations"
```

---

### Task 4: Preserve current multi-session and connector-delegation invariants

**Files:**
- No production changes expected.
- Test: `runtime/test_subscriber_session_identity.py`
- Test: `runtime/test_agent_auth.py`

**Interfaces:**
- Consumes: current `collab.bootstrap_agent`, `collab.session_heartbeat`, `ConnectorBinding`.
- Produces: regression evidence that session churn does not allocate a new public number and connector relay authority remains an explicit set.

- [ ] **Step 1: Run the session characterization**

Run:
```bash
/opt/eiros-control-plane/venv/bin/pytest -q runtime/test_subscriber_session_identity.py
```
Expected: PASS; two runtime sessions remain under the same installation record and same phone/subscriber routing value.

- [ ] **Step 2: Run the explicit connector-set characterization**

Run:
```bash
/opt/eiros-control-plane/venv/bin/pytest -q runtime/test_agent_auth.py -k 'trusted_connector_relay_stays_within_explicit_subscriber_set or case18_connector'
```
Expected: PASS; SUB-A is allowed only when explicitly bound and SUB-B rejects with `UnregisteredConnectorClaim`.

- [ ] **Step 3: Do not refactor either subsystem unless these characterization tests fail**

No code change is the expected result. Their current behavior already matches spec §8 items #3 and #7.

---

### Task 5: Verify cumulative GREEN without activating production

**Files:**
- Verify: entire repository
- Verify: `docs/superpowers/specs/2026-08-24-eiros-subscriber-identity-model.md`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: review SHA for independent Claude/ChatGPT verification; still no main merge or activation.

- [ ] **Step 1: Compile the touched Python modules**

Run:
```bash
/opt/eiros-control-plane/venv/bin/python -m py_compile runtime/agent_auth.py runtime/authenticated_collab.py runtime/collab.py
```
Expected: exit 0.

- [ ] **Step 2: Run the three focused contracts together**

Run:
```bash
/opt/eiros-control-plane/venv/bin/pytest -q \
  runtime/test_agent_auth.py \
  runtime/test_authenticated_collab.py \
  runtime/test_subscriber_session_identity.py
```
Expected: all PASS.

- [ ] **Step 3: Run the full suite**

Run:
```bash
/opt/eiros-control-plane/venv/bin/pytest -q
```
Expected: zero failures; the two existing FastAPI `on_event` deprecation warnings may remain until their unrelated migration.

- [ ] **Step 4: Check whitespace and worktree cleanliness**

Run:
```bash
git diff --check
git status --short --branch
```
Expected: diff-check clean and no uncommitted implementation files after the final commit.

- [ ] **Step 5: Independently review the exact GREEN SHA**

Send the exact SHA plus targeted/full-suite counts through EIROS Room. Reviewer must inspect the diff and rerun relevant tests before approving. Do not infer approval from prior review of c0b38ab/011ecad.

- [ ] **Step 6: Keep activation HOLD until the migration/recovery gates remain satisfied**

Do not merge to main or activate the new identity semantics merely because tests are green. Confirm the spec §9 activation gate, including the explicit migration path and the prohibition on ShadeChat's weak recovery mechanism.
