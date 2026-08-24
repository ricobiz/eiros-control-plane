# EIROS Subscriber Identity Model — reconciliation contract

Status: DRAFT FOR DUAL REVIEW — no production activation/merge.

## 1. Product invariant

EIROS exposes a phone-like public routing identity. The public callable identity is a **SubscriberNumber**, not a generic process/agent identity.

One SubscriberNumber identifies exactly one binding:

`human/user context × agent platform class × concrete device/installation`

A second device/installation for the same human and platform receives a different SubscriberNumber. Runtime sessions may churn or coexist below one recognized installation without changing that SubscriberNumber.

A public number is an address, never an authentication secret.

## 2. Entities

### PlatformClass
Stable host/platform class such as ChatGPT/OpenAI or Claude/Anthropic. It survives model-version changes. The public number prefix identifies PlatformClass; reserved prefixes do not imply a capability is actually live.

### Subscriber
Human-facing callable endpoint. Fields/invariants conceptually include:
- internal subscriber id
- platform class
- public SubscriberNumber
- one non-public DeviceBinding
- call/privacy policy
- lifecycle state

SubscriberNumber tail must be opaque/high-entropy/non-enumerable. It must not encode a reversible hardware/device identifier.

### DeviceBinding
Non-public stable recognition of one EIROS installation/device endpoint. Raw hardware identifiers must not be public routing data and should not be stored when an installation-scoped cryptographic identity can be used instead.

Target shape: device-held key material/OS-backed key where available plus a server-side non-public binding/fingerprint. Exact OS primitive is adapter-specific.

A key rotation may replace credential material for the same DeviceBinding; it does not create another independently callable actor sharing the same public number.

### SubscriberPrincipal
Cryptographic possession identity for the Subscriber's DeviceBinding. It authenticates requests for that Subscriber. The public SubscriberNumber is derived from trusted registry state after authentication, not from an untrusted body field.

### Session
Ephemeral runtime beneath a Subscriber/DeviceBinding. Multiple sessions may exist for one installation. A session is not a new Subscriber and does not get a new public number merely because a process/widget/app session restarted.

### ServicePrincipal
Non-human infrastructure actor: watchdog, headless service, server worker, trusted connector, scheduler, etc.

ServicePrincipal invariants:
- no public SubscriberNumber
- not discoverable/dialable as a human subscriber
- explicit scopes/authority
- may authenticate internal operations
- a TrustedConnector may be explicitly delegated to relay for selected SubscriberNumbers, but connector identity never becomes subscriber identity

### AuthContext
Server-created result of successful authentication. It must distinguish the authenticated principal from the optional human-callable subscriber actor.

Normative shape (names may change after review):
- `principal_id`
- `principal_type`
- `subscriber_number: str | None`
- `revocation_epoch`
- `authenticated_at`
- `scopes`
- `auth_method`

For a SubscriberPrincipal, `subscriber_number` is required and comes from trusted registry state. For a ServicePrincipal, `subscriber_number` is `None` unless a separate, explicit delegation adapter has authenticated/selected a subscriber on whose behalf it is relaying; that delegation must be represented separately from the connector's own identity.

### CallPolicy / Call
CallPolicy is per Subscriber. Minimum policy modes: Nobody/DND, Contacts/Allowlist, Ask, Everyone, with blocklist override. Unauthorized callers receive a neutral unavailable-style response where possible.

Call is signaling. It is not the Room itself.

### Room / Membership
Room is a durable private conference object with explicit ACL. URL/room id knowledge grants no authority. Membership references authenticated Subscriber identities, not arbitrary body-provided names.

Roles at minimum: Owner, Admin, Member. Read/send/invite/admin/recovery capabilities are separable. Adding a member may grant authorized historical context. Removal rotates future key epoch; it cannot erase already learned history.

### RecoveryCapability
Recovery restores **Room authorization**, not the old device-bound SubscriberNumber. A lost device is replaced by a new device/installation and therefore a new SubscriberNumber; recovery or an existing Admin can authorize that new Subscriber into the Room.

Recovery plaintext must never be written to prompts, Room history, telemetry or ordinary logs. Final implementation requires high entropy and a cryptographically sound verifier/wrapping design.

## 3. DDCHAT1 / ShadeChat source audit

Observed legacy source behavior:
- `getSessionId()` reads `localStorage['shade-session-id']`; absent => `crypto.randomUUID()` and stores it locally.
- Room ownership/membership is keyed by session id (`ownerId=sessionId`, `members[sessionId]`).
- Same session re-enters directly. Same nickname under a different session enters recovery flow.
- Recovery code is six characters from `ABCDEFGHJKLMNPQRSTUVWXYZ23456789` generated with `Math.random()`.
- Successful recovery transfers membership to the new session and records `recoveredFrom`.
- Without the code, a join-request can be approved/denied by an admin; client polls every two seconds and stops after five minutes.
- Invite state uses `shade-invites` and `shade-invite-claims`; used/claimed invite is treated as burned.
- Retrieved source shows no `crypto.subtle`, encryption/decryption, HMAC, hashing or digital signature layer. Identity/profile/recovery state is plaintext localStorage/shared records in the observed implementation.

Conclusion: **reuse ShadeChat's passwordless UX and recovery/membership semantics, not its security mechanism.** EIROS must replace the six-character `Math.random()` recovery and plaintext trust model with real cryptographic possession and high-entropy recovery capability.

## 4. What survives from c0b38ab

Keep conceptually:
- trusted AuthContext created only after verification
- body identity is assertion-only; mismatch rejects
- canonical signed envelope binding method + payload hash + principal + explicit integer timestamp + request id
- atomic replay `consume_once`
- revocation and bearer expiry distinction
- explicit scopes
- transport-neutral verifier/adapters
- explicit ConnectorBinding/delegation concept

These are orthogonal to public subscriber cardinality.

## 5. What conflicts in c0b38ab

The conflict is concrete, not global:
- `PrincipalRegistry._by_agent_number: dict[str, set[str]]`
- `agent_number_members()`
- `verify_signed_request()` accepts any registered principal that belongs to that number's membership set
- `test_multiple_principals_can_share_one_agent_number()` deliberately binds both `INTERACTIVE_INSTALLATION` and `HEADLESS_SERVICE` to one public `AGN-SHARED`

That old model conflates public callable identity with infrastructure principals and is no longer valid.

Required semantic delta:
1. One public SubscriberNumber is bound to one device/installation subscriber identity, not a heterogeneous set of principals.
2. Headless/watchdog/worker/connector principals are non-dialable ServicePrincipals and do not acquire a SubscriberNumber merely to authenticate.
3. Multiple runtime sessions belong below the Subscriber/DeviceBinding, not beside it as separate public-number principals.
4. Public-number substitution remains rejected after signature verification; unknown subscriber and mismatched subscriber remain distinct failure classes if that distinction is still useful without leaking externally.
5. Connector relay authorization remains explicit, but connector identity must not be returned as the human subscriber actor.

## 6. What survives from 011ecad

The facade's security invariant survives:
- derive actor from AuthContext
- treat body `from_agent`/`agent_id` only as an assertion
- mismatch rejects before calling the collab engine

Required delta is naming/actor resolution:
- `_actor()` must resolve an authenticated Subscriber actor, not blindly `return auth.agent_number`
- ServicePrincipal contexts must not silently enter human subscriber collaboration mutations
- legacy engine fields may temporarily stay named `agent_id/from_agent` behind a migration adapter, but authority comes from SubscriberNumber/typed actor identity

## 7. Current collab.py gap

Current production bootstrap already allocates distinct `phone_number` records when `platform + instance_id` differs, which is directionally compatible with device/install cardinality. It is not sufficient security:
- `instance_id` is not yet cryptographic possession proof
- current phone numbers are sequential/enumerable
- `agent_id`, service identities and human-callable identities are still mixed in one agent store
- presence/session tracking is widget/runtime-oriented, not semantic subscriber presence

Do not mistake the current phone-number field for the final SubscriberNumber security model.

## 8. RED contract to write before implementation

The next tests should prove behavior, not merely renaming:
1. registering a second independent interactive installation against an already-bound public subscriber number is rejected
2. a HEADLESS_SERVICE/WATCHDOG/SERVER_WORKER/TRUSTED_CONNECTOR cannot register as a public callable subscriber
3. multiple runtime sessions for the same subscriber remain valid without allocating a second public number
4. signed request for Subscriber A cannot claim Subscriber B even with a valid A credential
5. service authentication produces a service AuthContext without a callable subscriber actor
6. collaboration facade rejects a ServicePrincipal attempting a subscriber-only mutation unless an explicit delegation adapter produces a subscriber-authorized context
7. trusted connector relay is limited to its explicit delegated subscriber set and does not widen authority
8. existing replay/revocation/scope/method+payload/timestamp tests remain green after the model split

## 9. Activation gate

No merge/activation until:
- revised entity/cardinality contract is dual-reviewed
- RED tests fail for the intended old-model reasons
- implementation turns them GREEN
- full suite remains green
- old c0b38ab/011ecad security regressions remain covered
- migration path for current collab `agent_id`/`phone_number` is explicit
- recovery implementation does not reuse ShadeChat's weak six-character/plaintext mechanism

## 10. Migration path from current `agent_id` / `phone_number`

The current collaboration store is a compatibility substrate, not the final authority model. Migration must be additive first and must not silently promote today's sequential `phone_number` values into trusted SubscriberNumbers.

1. **Keep `agent_id` as an internal engine key during transition.** Existing dialogue/project APIs may continue to address the legacy engine record by `agent_id`, but authentication and public routing authority come from the authenticated Subscriber mapping, not from a caller-supplied `agent_id`.
2. **Treat current `phone_number` as legacy routing metadata only.** Values such as `100001`/`100002` are sequential and enumerable. They must not become final public SubscriberNumbers and must never authenticate a caller.
3. **Re-enrol each existing interactive installation.** A recognized `platform_class + installation` must establish the new DeviceBinding/possession proof and receive a new opaque high-entropy SubscriberNumber. Reconnecting the same enrolled installation reuses that SubscriberNumber; a different installation receives another one.
4. **Maintain a server-side compatibility mapping during rollout.** The authenticated Subscriber maps to the legacy internal `agent_id` used by the current collab engine. This adapter permits gradual migration of engine field names without letting legacy body fields become authority.
5. **Do not create Subscriber mappings for infrastructure principals.** Watchdogs, workers, headless services and trusted connectors stay ServicePrincipals. A connector may hold an explicit delegation set of SubscriberNumbers, but the connector itself has no public callable number.
6. **Keep runtime sessions below the migrated Subscriber.** Existing `sessions` entries remain ephemeral children of the same enrolled installation and do not allocate new public numbers.
7. **Retire legacy public lookup deliberately.** Any temporary acceptance of old numeric aliases is compatibility-only, non-authenticating and should be limited to trusted/internal migration paths. New directory/call surfaces expose only SubscriberNumber. Once active installations are re-enrolled, external dialing by legacy sequential `phone_number` is removed.
8. **No automatic identity transplant.** If an old installation cannot prove the new DeviceBinding, it does not inherit the old endpoint merely by presenting `agent_id`, display name, legacy `phone_number`, or self-asserted `instance_id`. It enrolls as a new Subscriber and regains Room authority only through the separate recovery/admin-approval flow.

Migration cutover is complete only when public directory/call routing uses SubscriberNumber, subscriber-only mutations derive their legacy engine actor through the authenticated mapping, ServicePrincipals remain non-dialable, and no external authorization decision depends on the old sequential `phone_number` or body-provided `agent_id`.
