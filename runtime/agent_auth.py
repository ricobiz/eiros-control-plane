"""Transport-neutral caller-authentication domain for EIROS.

Pure domain module: no FastMCP/HTTP/stdio/tunnel imports here. Per-transport
adapters (Claude HTTP bearer/token_verifier, ChatGPT tunnel connector,
watchdog credential-file) live elsewhere and translate into calls on this
module's API. See project_state(eiros-hub).identity_and_auth_2026_08_22 and
.threat_model_matrix_v1 for the design this file implements the contract of.

Revision 2: amended per chatgpt's independent review (seq193) of the first
tests-only SHA 0f0056d. AuthContext gained `scopes`/`auth_method`. Added
SignatureVerifier (typing.Protocol, no implementation) plus
canonical_envelope()/hash_payload() pure helpers, and an optional
`verifier` param on AuthStore.__init__, so tests inject a deterministic
signer instead of asserting against placeholder bytes that could never
actually verify.

Revision 3: amended per chatgpt's seq195 design decision, resolving
revision 2's open question (how to distinguish InvalidCredential/case3
from PayloadTampered/case15 at verification time). verify_signed_request
now takes an explicit `payload_hash_claim` - the hash declared inside the
signed envelope - separate from `payload`, the bytes actually received.
Verification precedence (documented on verify_signed_request itself):
hash(received payload) vs payload_hash_claim is checked FIRST, before
signature verification; a mismatch is PayloadTampered regardless of
whether the signature would otherwise verify. Only once the hashes match
does signature verification run, where failure is InvalidCredential. This
gives the two failure modes a real observable basis instead of one
ambiguous signature-check failure standing in for both.

Revision 4 (GREEN, 2026-08-23, claude): real implementation against the
753d3f7 RED contract - all 15 threat_model_matrix_v1 cases below now pass
for real, not via NotImplementedError. Two things surfaced only by
actually implementing this (not visible from reading the skeleton):

  1. PrincipalRegistry had no way to retrieve a registered principal's
     PrincipalType when constructing an AuthContext - register_principal
     accepts one, but nothing read it back. Added principal_type_for().
     This is purely additive: no existing test enumerates or constrains
     PrincipalRegistry's method set, and all 15 cases still pass. Flagged
     to chatgpt in the GREEN report rather than landed silently, since
     both agents already reviewed this file's RED shape once.

  2. Bearer tokens and signed requests need two DIFFERENT revocation
     checks, not one shared comparison. A bearer token is a standing
     credential minted once and reused, so it carries its own
     issued_epoch and must be checked against the CURRENT epoch every
     time (case 6: revoked but not yet expired -> still rejected). A
     signed request has no stored "epoch at signing time" at all - it is
     freshly authenticated on every call from a live credential - so
     there is nothing to pin it to except "has this principal ever been
     revoked" (current_revocation_epoch != 0). Both paths satisfy the
     same PrincipalRevoked contract; they just have different baselines
     to compare against, for a structural reason, not an inconsistency.

Revision 5 (2026-08-23, claude): fixes six real defects chatgpt's
independent execution-based review of GREEN SHA 7e70a7a found (seq206,
the operative consolidated review after an overlapping seq205 - see
seq207's correction). Not cosmetic: findings 1 and 2 below are genuine
auth-bypass classes, reproduced by execution before being fixed, not
merely inspected.

  1. agent_number -> principal_id was single-owner (_by_agent_number:
     dict[str, str]). The approved identity model (project_state
     identity_and_auth_2026_08_22.vocabulary) is that one stable
     agent_number identifies one AGENT, and several principals
     (browser/app/watchdog/...) may legitimately share it. The old model
     let a second legitimate registration silently DISPLACE the first
     (last-write-wins on a dict key) instead of coexisting, breaking the
     first principal's own genuinely-valid requests. NOTE: seq205 (a
     since-superseded, overlapping review message) initially recommended
     the OPPOSITE fix - rejecting duplicate agent_number registration
     outright. seq207 explicitly corrected this: that recommendation was
     wrong and was NOT implemented. Reverse lookup is now agent_number ->
     set-of-principal_ids (membership); a principal_id itself is still
     bound to exactly one agent_number (unchanged) - only the reverse
     direction is many-valued. verify_signed_request's case 2/12 check
     changed from "is this the sole owner" to "is this principal a member
     of this agent_number's set".

  2. Revocation was bypassable two ways. (a) issue_bearer_token did not
     check revocation at issuance time at all: minting a token for an
     already-revoked principal stamped the token's own issued_epoch from
     the (already-revoked) current epoch, so the existing epoch-pinned
     check in verify_bearer_token (current_epoch != issued_epoch) held
     trivially true forever - epoch-pinning only ever detected revocation
     that happened AFTER issuance, never revocation already in effect AT
     issuance. Fixed: issuance itself now refuses a currently-revoked
     principal. (b) register_principal unconditionally overwrote any
     existing record, silently resetting revocation_epoch back to 0 on
     re-registration - so ANY caller able to invoke register_principal
     again (accidentally or otherwise) could undo a revocation. Fixed:
     register_principal is now idempotent for an EXACT repeat of the same
     principal_id's (agent_number, principal_type, credential, scopes) -
     a harmless no-op that leaves revocation_epoch untouched - and raises
     ConflictingPrincipalRegistration for any re-registration attempt that
     changes those fields. Deliberate non-goal: neither fix adds
     revoked-principal reactivation/credential-rotation semantics - there
     is no agreed design for that yet, and silently allowing it via
     re-registration or re-issuance is exactly the bypass being closed,
     not a shortcut to it.

  3. The replay-request cache (_seen_requests) was a private dict owned
     directly by one AuthStore instance, so replay protection evaporated
     on every AuthStore reconstruction (e.g. process restart) - a
     resubmitted request_id was rejected by the instance that first saw
     it, but accepted by a fresh instance over the same registry. Fixed:
     replay state now lives behind an injectable ReplayStore protocol
     (default InMemoryReplayStore preserves the old zero-config
     behaviour for tests/single-process use); two AuthStore instances
     constructed with the SAME ReplayStore instance now correctly observe
     each other's burned nonces, and a real deployment can inject a
     persistent-backed implementation of the same protocol instead.

  4. AuthContext.scopes was structurally present since revision 2 but no
     code path ever populated it - always (). Fixed: PrincipalRegistry
     now stores a scopes grant per principal (registration-time input,
     default empty, backward compatible); verify_signed_request resolves
     scopes LIVE from the registry on every call (a grant/revocation
     change takes effect on the very next signed request, matching
     revocation_epoch's own freshness model); issue_bearer_token bakes
     scopes into the BearerToken snapshot at issuance time and
     verify_bearer_token returns exactly that snapshot, never re-read
     afterward (matching the point-in-time model epoch-pinning already
     uses for bearer tokens). AuthContext.scopes and BearerToken.scopes
     changed type from tuple[str, ...] to frozenset[str] - scopes are an
     unordered capability set, not a sequence.

  5. canonical_envelope() did not bind the MCP/tool method being called,
     despite the frozen signed-request model covering
     "method + canonical payload hash + timestamp/request_id + identity".
     A signature was therefore transferable verbatim between two
     different methods sharing the same payload bytes, timestamp and
     request_id - the signature said "this payload, this principal, this
     moment" but never "this specific operation". Fixed: canonical_envelope
     and verify_signed_request both gained a required `method` parameter,
     bound into the signed bytes; resubmitting a genuinely-valid signed
     envelope under a different method now fails signature verification
     (InvalidCredential) rather than succeeding.

  6. The envelope encoding was delimiter-joined
     (f"{a}|{b}|{c}|{d}|{e}"), which is ambiguous whenever a field itself
     may contain the delimiter - e.g. principal_id="a|b", agent_number="c"
     and principal_id="a", agent_number="b|c" both serialized to the
     identical bytes b"a|b|c|...", making two DIFFERENT logical envelopes
     mutually forgeable under the same signature. Reproduced as an actual
     byte-for-byte collision before fixing. Fixed: fields are now
     length-prefixed (4-byte big-endian length + raw UTF-8 bytes) rather
     than delimiter-joined, and `timestamp` is frozen to an integer
     number of milliseconds since the epoch rather than interpolated as a
     raw float - float repr is not a stable cross-language canonical
     format, and any future non-Python signer must reproduce these exact
     bytes from the same wall-clock instant.

Threat-matrix case numbers below match threat_model_matrix_v1 verbatim.
"""
from __future__ import annotations

import dataclasses
import enum
import hashlib
import secrets
import typing

# Resolved design constants (agreed 2026-08-22, see project_state
# identity_and_auth_2026_08_22.claude_refinements_2026_08_22_resolved item 2).
ALLOWED_CLOCK_SKEW_SECONDS: float = 120.0
REPLAY_WINDOW_SECONDS: float = 600.0


class PrincipalType(enum.Enum):
    INTERACTIVE_INSTALLATION = "interactive_installation"
    HEADLESS_SERVICE = "headless_service"
    WATCHDOG = "watchdog"
    SERVER_WORKER = "server_worker"
    # Coarse, connector-level trust-aggregation identity for the ChatGPT
    # tunnel-client (proposed by claude 2026-08-22, accepted by chatgpt
    # seq189). See ConnectorBinding below for case 18.
    TRUSTED_CONNECTOR = "trusted_connector"


class AuthError(Exception):
    """Base class for every caller-authentication failure."""


class NoAuthProvided(AuthError):
    """Case 1: request carries no credential/signature/bearer token at all."""


class UnknownAgentNumber(AuthError):
    """Case 2: the claimed agent_number has NO backing registered principal
    at all (threat_model_matrix_v1's own wording) - i.e. its membership set
    is empty. Must be distinguishable from AgentNumberMismatch (case 12):
    case 2 is "this number belongs to nobody"; case 12 is "this number has
    one or more legitimate members, and the caller's own credential is
    genuinely valid, but the caller isn't among them"."""


class InvalidCredential(AuthError):
    """Case 3: the signature does not verify against the claimed
    principal's own key, for an envelope whose declared payload_hash_claim
    DOES match the actually-received payload (see verify_signed_request's
    docstring for the full precedence rule vs PayloadTampered/case 15).
    Also raised for a bearer token string this store never issued, for a
    signed request whose principal_id is not registered at all (fails
    closed as "not a credential we recognize" rather than leaking whether
    the principal_id exists), and - since revision 5 - for a genuinely
    valid signature resubmitted under a DIFFERENT method than the one it
    was actually signed for (canonical_envelope binds method; a mismatched
    method changes the signed bytes, so verification fails the same way a
    wrong key would)."""


class ReplayedRequest(AuthError):
    """Case 4: request_id already seen for this principal within
    REPLAY_WINDOW_SECONDS. Since revision 5, "seen" is answered by the
    AuthStore's injected ReplayStore, which may be shared across multiple
    AuthStore instances (see ReplayStore/InMemoryReplayStore below) -
    replay protection is no longer scoped to one process's lifetime by
    construction."""


class PrincipalRevoked(AuthError):
    """Cases 5 and 6: the principal's CURRENT revocation_epoch is ahead of
    the epoch bound to the credential/token being verified. Must be checked
    fresh on every verification, including for an otherwise-still-valid
    cached bearer token (case 6) - never deferred to TTL expiry. Since
    revision 5, also raised by issue_bearer_token itself when the
    principal is ALREADY revoked at issuance time (epoch-pinning alone
    cannot catch that case - see the module docstring's Revision 5 note
    #2)."""


class ClockSkewExceeded(AuthError):
    """Case 11: |now - request timestamp| > ALLOWED_CLOCK_SKEW_SECONDS.
    Boundary is inclusive: exactly ALLOWED_CLOCK_SKEW_SECONDS is accepted,
    any amount past it is rejected."""


class AgentNumberMismatch(AuthError):
    """Case 12: signature/token is genuinely valid for principal P, but P
    is not among the principals bound to the claimed agent_number B (B may
    be legitimately bound to one or more OTHER principals - see the module
    docstring's Revision 5 note #1 on the multi-principal-per-agent_number
    model). See UnknownAgentNumber for the case where B has no bound
    principals at all (case 2)."""


class PayloadTampered(AuthError):
    """Case 15: hash_payload(the ACTUALLY RECEIVED payload bytes) does not
    match payload_hash_claim - the hash declared inside the envelope that
    was signed. Checked BEFORE signature verification (see
    verify_signed_request), so this fires regardless of whether the
    signature would otherwise verify. Distinct from InvalidCredential
    (case 3): here the declared/received payload hashes disagree; there,
    the hashes agree but the signature itself doesn't verify."""


class TokenExpired(AuthError):
    """Case 16: bearer/session token used after its own TTL/expires_at,
    with NO revocation involved - must be distinguishable from
    PrincipalRevoked (case 6) as a separate code path, not conflated."""


class IdentityMismatch(AuthError):
    """Case 17: the body-supplied agent_id/from_agent field does not match
    the server-derived AuthContext for this request. The body claim is
    NEVER trusted as identity on its own, only as a value to cross-check.
    NOTE for collab-layer callers (e.g. runtime/authenticated_collab.py):
    reuse THIS class rather than defining a parallel identity-mismatch
    exception - single source of truth for the auth-domain error taxonomy
    (chatgpt agreed, seq195: authenticated_collab.py will unify onto this).
    """


class UnregisteredConnectorClaim(AuthError):
    """Case 18: connector-level transport auth succeeded (e.g. the ChatGPT
    tunnel-client's own service credential verified), but the request
    claims an agent_number/principal that is not in that connector's
    registered binding. Connector-level trust must never imply
    identity-level trust for an arbitrary claim."""


@dataclasses.dataclass(frozen=True)
class AuthContext:
    """Server-derived identity for one request. Constructed ONLY by
    AuthStore/adapters from a verified credential - never constructed from
    client-supplied body fields directly (see IdentityMismatch / case 17).

    scopes/auth_method added in revision 2 (chatgpt seq193 review): without
    scopes, principal_type alone cannot keep bootstrap/register/operator/
    control as separate authorities from plain collab mutation - two
    interactive_installation principals could need different allowed
    scopes. auth_method records which verification path produced this
    context (e.g. "bearer_token" | "signed_request"), for audit/future
    higher-assurance-path enforcement. Confirmed sufficient for slice 1 by
    chatgpt (seq195) - a separate credential/session identifier is
    deferred to transport adapters/session binding, not blocking here.

    Revision 5: scopes is now actually populated (see module docstring
    Revision 5 note #4) and changed type from tuple[str, ...] to
    frozenset[str] - an unordered capability set, not a sequence.
    """

    principal_id: str
    agent_number: str
    principal_type: "PrincipalType"
    revocation_epoch: int
    authenticated_at: float
    scopes: "frozenset[str]" = frozenset()
    auth_method: str = ""


@dataclasses.dataclass(frozen=True)
class BearerToken:
    """Minted after asymmetric principal-keypair proof; used for ongoing
    per-request auth on the Claude HTTP path (FastMCP token_verifier).

    Revision 5: gained `scopes`, a snapshot of the principal's granted
    scopes taken at issuance time (see module docstring Revision 5 note
    #4) - deliberately NOT re-read from the registry on every verification,
    matching the same point-in-time model issued_epoch already uses.
    """

    token: str
    principal_id: str
    issued_epoch: int
    issued_at: float
    expires_at: float
    scopes: "frozenset[str]" = frozenset()


class SignatureVerifier(typing.Protocol):
    """Pluggable signature backend, injected into AuthStore (revision 2).
    The product path injects a real asymmetric verifier; tests inject a
    deterministic HMAC-based one (see test_agent_auth.py). Purely
    structural typing - no implementation lives here, matching this
    file's tests-only-skeleton status."""

    def sign(self, envelope: bytes, credential: bytes) -> bytes: ...

    def verify(self, envelope: bytes, signature: bytes, credential: bytes) -> bool: ...


class ReplayStore(typing.Protocol):
    """Pluggable request-replay backend (revision 5, chatgpt seq206 finding
    #3). AuthStore no longer owns replay state as an unconditionally
    private instance dict - that made replay protection evaporate on every
    AuthStore reconstruction, which is not "replay protection" for a
    credential meant to survive process restarts. Two AuthStore instances
    constructed with the SAME ReplayStore instance (or, in a real
    deployment, the same persistent-backed implementation of this
    protocol) observe each other's burned nonces. Purely structural
    typing, matching SignatureVerifier's style."""

    def seen(self, principal_id: str, request_id: str, now: float, window_seconds: float) -> bool: ...

    def mark(self, principal_id: str, request_id: str, now: float) -> None: ...

    def prune(self, now: float, window_seconds: float) -> None: ...


class InMemoryReplayStore:
    """Default ReplayStore (revision 5) - process-local dict, exactly what
    AuthStore used to hardcode internally as a private attribute. Fine for
    tests and single-process deployments, and for sharing across multiple
    AuthStore instances IN THE SAME PROCESS when the same
    InMemoryReplayStore instance is injected into each. NOT restart-safe by
    itself - a real multi-process/restart-safe deployment must inject a
    persistent-backed implementation of the same ReplayStore protocol
    instead."""

    def __init__(self) -> None:
        self._seen: dict[tuple[str, str], float] = {}

    def seen(self, principal_id: str, request_id: str, now: float, window_seconds: float) -> bool:
        last_used = self._seen.get((principal_id, request_id))
        return last_used is not None and (now - last_used) <= window_seconds

    def mark(self, principal_id: str, request_id: str, now: float) -> None:
        self._seen[(principal_id, request_id)] = now

    def prune(self, now: float, window_seconds: float) -> None:
        """Lazy sweep. Entries older than window_seconds can never again
        cause a false ReplayedRequest, so there is no correctness reason to
        keep them - only a memory-growth reason to drop them."""
        expired = [key for key, used_at in self._seen.items() if now - used_at > window_seconds]
        for key in expired:
            del self._seen[key]


def hash_payload(payload: bytes) -> str:
    """Single canonical definition of "payload hash" - both test fixtures
    and any real implementation must use this, not hand-rolled hashing, so
    a declared payload_hash_claim is comparable to a freshly-received
    payload's hash (see verify_signed_request). Pure data transform."""
    return hashlib.sha256(payload).hexdigest()


def canonical_envelope(
    *,
    principal_id: str,
    agent_number: str,
    method: str,
    timestamp: float,
    request_id: str,
    payload_hash: str,
) -> bytes:
    """The exact bytes a SignatureVerifier signs/verifies over. Binds
    principal_id, agent_number, method, timestamp, request_id and the
    DECLARED payload hash together (this `payload_hash` is what
    verify_signed_request calls payload_hash_claim once it arrives over
    the wire), so a signature cannot be silently replayed against a
    different payload, principal, agent_number claim, or - since revision
    5 - a different method. Pure data transform - no crypto, no decision
    logic.

    Note this is also what makes agent_number_claim itself tamper-evident:
    unlike payload (large, so only its hash is embedded), agent_number is
    short enough to embed directly - so verifying the signature over this
    envelope already proves agent_number_claim is what principal_id
    actually signed, before verify_signed_request trusts it for the case
    2/12 membership check.

    Revision 5 encoding change (chatgpt seq206 findings #5 and #6):
      - `method` (the MCP/tool method this envelope authorizes) is now a
        bound field. Without it, a valid signature for one method's call
        was transferable verbatim to any other method sharing the same
        payload bytes, timestamp and request_id - the signature said
        "this payload, this principal, this moment" but never "this
        operation". A caller resubmitting a captured envelope under a
        different method must now fail verification.
      - Fields are length-prefixed (4-byte big-endian length + raw UTF-8
        bytes) rather than delimiter-joined. A delimiter-joined
        f"{a}|{b}|..." string is ambiguous whenever a field itself may
        contain the delimiter - reproduced as a real collision:
        principal_id="a|b", agent_number="c" and principal_id="a",
        agent_number="b|c" both serialized to the identical bytes
        b"a|b|c|...", making two DIFFERENT logical envelopes mutually
        forgeable under the same signature. Length-prefixing makes the
        byte boundary between fields unambiguous regardless of content.
      - `timestamp` is frozen to an integer number of milliseconds since
        the epoch (round(timestamp * 1000)) rather than interpolated as a
        raw float: float repr is not a stable cross-language canonical
        format (formatting, trailing zeros and precision differ across
        runtimes), and any future non-Python signer must be able to
        reproduce these exact bytes from the same wall-clock instant.
        Millisecond precision is finer than this module's whole-second
        clock-skew/replay granularity, so it does not lose information
        those checks depend on.
    """
    fields = (
        principal_id.encode("utf-8"),
        agent_number.encode("utf-8"),
        method.encode("utf-8"),
        str(int(round(timestamp * 1000))).encode("ascii"),
        request_id.encode("utf-8"),
        payload_hash.encode("utf-8"),
    )
    parts: list[bytes] = []
    for field in fields:
        parts.append(len(field).to_bytes(4, "big"))
        parts.append(field)
    return b"".join(parts)


class ConflictingPrincipalRegistration(AuthError):
    """Not a threat_model_matrix_v1 case - a PrincipalRegistry data-
    integrity error (revision 5, chatgpt seq206 finding #2b). Raised by
    register_principal when principal_id is already registered with a
    DIFFERENT agent_number, principal_type, credential or scopes than the
    incoming call. Re-registering the SAME principal_id with IDENTICAL
    data is a no-op (idempotent) and does NOT raise - this lets a caller
    safely retry registration without accidentally resetting
    revocation_epoch back to 0, while still catching a genuine attempt to
    silently rebind an existing principal_id to different material."""


class PrincipalRegistry:
    """Source of truth for registered principals: agent_number binding,
    principal_type, credential material, granted scopes, and current
    revocation_epoch. agent_number itself is server-assigned/opaque/
    high-entropy elsewhere (registration flow, not this module) - this
    registry only stores the resulting binding.

    In-memory reference implementation (revision 4, GREEN). Real production
    wiring is expected to back this with a persistent store - this module
    stays transport- and storage-neutral, so any persistent-backed registry
    just needs to satisfy this same method contract.

    Revision 5 (2026-08-23, claude, per chatgpt seq206/207 review of GREEN
    SHA 7e70a7a): two structural fixes, both described in full in the
    module docstring's Revision 5 note - summarized here:

      1. agent_number -> principal_id was single-owner. The approved
         identity model allows several principals to legitimately share
         one agent_number. Reverse lookup is now agent_number ->
         set-of-principal_ids (see agent_number_members, which replaces
         the removed single-owner principal_for_agent_number).

      2. register_principal unconditionally overwrote any existing
         record, including silently resetting revocation_epoch back to 0
         on re-registration - a real revocation-bypass path, not a
         cosmetic gap. register_principal is now idempotent for an exact
         repeat of the same principal_id's data (no-op, revocation_epoch
         untouched) and raises ConflictingPrincipalRegistration for a
         conflicting re-registration attempt.

    Also gained scopes_for() (Revision 5 note #4): the principal's
    currently-granted scopes, read live by verify_signed_request on every
    call, and baked into a BearerToken snapshot once at issuance time.
    """

    def __init__(self) -> None:
        self._principals: dict[str, dict[str, object]] = {}
        self._by_agent_number: dict[str, set[str]] = {}

    def register_principal(
        self,
        principal_id: str,
        agent_number: str,
        principal_type: "PrincipalType",
        credential: bytes,
        scopes: "frozenset[str]" = frozenset(),
    ) -> None:
        existing = self._principals.get(principal_id)
        if existing is not None:
            unchanged = (
                existing["agent_number"] == agent_number
                and existing["principal_type"] == principal_type
                and existing["credential"] == credential
                and existing["scopes"] == scopes
            )
            if unchanged:
                # Idempotent no-op - revocation_epoch is deliberately left
                # untouched (see ConflictingPrincipalRegistration docstring
                # and module docstring Revision 5 note #2b).
                return
            raise ConflictingPrincipalRegistration(
                f"principal_id {principal_id!r} is already registered with a "
                f"different agent_number/principal_type/credential/scopes"
            )
        self._principals[principal_id] = {
            "agent_number": agent_number,
            "principal_type": principal_type,
            "credential": credential,
            "scopes": scopes,
            "revocation_epoch": 0,
        }
        self._by_agent_number.setdefault(agent_number, set()).add(principal_id)

    def revoke_principal(self, principal_id: str) -> None:
        """Advances the principal's revocation_epoch by exactly one. Must be
        observed by the very next verification of ANY credential for this
        principal, including already-issued cached bearer tokens (case 6),
        and - since revision 5 - blocks issuance of any NEW bearer token
        for this principal until the caller re-registers/rotates in an
        explicit, not-yet-designed reactivation flow."""
        record = self._principals[principal_id]
        record["revocation_epoch"] = int(record["revocation_epoch"]) + 1

    def current_revocation_epoch(self, principal_id: str) -> int:
        return int(self._principals[principal_id]["revocation_epoch"])

    def agent_number_for(self, principal_id: str) -> str:
        return str(self._principals[principal_id]["agent_number"])

    def principal_type_for(self, principal_id: str) -> "PrincipalType":
        """Added in revision 4 (GREEN): AuthContext requires principal_type
        and nothing in the original tests-only skeleton could retrieve it
        back out of the registry. See the module docstring's Revision 4
        note - purely additive, does not change any of the 15 already
        RED-then-GREEN test cases' expected behavior."""
        return typing.cast(PrincipalType, self._principals[principal_id]["principal_type"])

    def credential_for(self, principal_id: str) -> bytes:
        return typing.cast(bytes, self._principals[principal_id]["credential"])

    def scopes_for(self, principal_id: str) -> "frozenset[str]":
        """Added revision 5 (chatgpt seq206 finding #4): the principal's
        currently-granted scopes. Read LIVE by verify_signed_request on
        every call (a scope grant/revocation change takes effect on the
        very next signed request, same freshness model as revocation_epoch
        itself); baked into the BearerToken snapshot at issuance time by
        issue_bearer_token and NOT re-read afterward (same point-in-time
        model epoch-pinning already uses for bearer tokens - see AuthStore
        Revision 4/5 notes)."""
        return typing.cast("frozenset[str]", self._principals[principal_id]["scopes"])

    def agent_number_members(self, agent_number: str) -> "frozenset[str]":
        """Added revision 5, replaces the removed principal_for_agent_number
        (its single-owner return type was structurally incompatible with
        the approved multi-principal-per-agent_number model - see class
        docstring Revision 5 note #1). An empty result means case 2
        territory (nobody bound to this agent_number); a non-empty result
        not containing the caller's own principal_id means case 12
        territory. Returns a fresh frozenset snapshot - callers cannot
        mutate registry state through the return value."""
        return frozenset(self._by_agent_number.get(agent_number, ()))


class AuthStore:
    """Issues and verifies bearer tokens and signed requests against a
    PrincipalRegistry. Transport-neutral: adapters call in with whatever
    they received (header value, stdio payload field, ...) and get back an
    AuthContext, or an AuthError subclass is raised.

    Revision 5: gained an injectable `replay_store` (see ReplayStore /
    InMemoryReplayStore above and module docstring Revision 5 note #3) -
    replay state is no longer unconditionally private to one AuthStore
    instance.
    """

    def __init__(
        self,
        registry: "PrincipalRegistry",
        *,
        verifier: "SignatureVerifier | None" = None,
        replay_store: "ReplayStore | None" = None,
    ) -> None:
        self._registry = registry
        self._verifier = verifier
        self._tokens: dict[str, BearerToken] = {}
        self._replay_store: "ReplayStore" = replay_store if replay_store is not None else InMemoryReplayStore()

    def issue_bearer_token(self, principal_id: str, ttl_seconds: float, now: float) -> "BearerToken":
        issued_epoch = self._registry.current_revocation_epoch(principal_id)
        if issued_epoch != 0:
            # Revision 5 (chatgpt seq206 finding #2a): minting a token for
            # an already-revoked principal previously succeeded, and then
            # VERIFIED successfully too - the token's own issued_epoch
            # snapshot was taken from the already-revoked current epoch, so
            # current_epoch == issued_epoch held trivially at verify time.
            # Epoch-pinning only ever detects revocation that happens AFTER
            # issuance; this closes the "already revoked before issuance"
            # gap by refusing to mint at all. See module docstring Revision
            # 5 note #2 for why this deliberately does not add
            # reactivation/credential-rotation semantics.
            raise PrincipalRevoked(f"principal {principal_id!r} is revoked; refusing to issue a new bearer token")
        token = BearerToken(
            token=secrets.token_urlsafe(32),
            principal_id=principal_id,
            issued_epoch=issued_epoch,
            issued_at=now,
            expires_at=now + ttl_seconds,
            scopes=self._registry.scopes_for(principal_id),
        )
        self._tokens[token.token] = token
        return token

    def verify_bearer_token(self, token: "str | None", now: float) -> "AuthContext":
        """Raises NoAuthProvided / UnknownAgentNumber / InvalidCredential /
        TokenExpired / PrincipalRevoked as appropriate, in that logical
        precedence (missing before malformed before expired before
        revoked-state, though revocation is ALWAYS re-checked regardless of
        which other checks already passed - see PrincipalRevoked)."""
        if not token:
            raise NoAuthProvided("no bearer token provided")

        bearer = self._tokens.get(token)
        if bearer is None:
            # A token string this store never issued is indistinguishable,
            # from the outside, from a forged/garbage credential.
            raise InvalidCredential("bearer token not recognized")

        if now > bearer.expires_at:
            raise TokenExpired(f"bearer token for {bearer.principal_id!r} expired at {bearer.expires_at}")

        current_epoch = self._registry.current_revocation_epoch(bearer.principal_id)
        if current_epoch != bearer.issued_epoch:
            # Epoch-pinned: this cached token was minted under an epoch that
            # has since moved, regardless of remaining TTL (case 6).
            raise PrincipalRevoked(f"principal {bearer.principal_id!r} revoked since token issuance")

        return AuthContext(
            principal_id=bearer.principal_id,
            agent_number=self._registry.agent_number_for(bearer.principal_id),
            principal_type=self._registry.principal_type_for(bearer.principal_id),
            revocation_epoch=current_epoch,
            authenticated_at=now,
            scopes=bearer.scopes,
            auth_method="bearer_token",
        )

    def verify_signed_request(
        self,
        *,
        principal_id: str,
        agent_number_claim: str,
        method: str,
        payload: bytes,
        payload_hash_claim: str,
        signature: bytes,
        timestamp: float,
        request_id: str,
        now: float,
    ) -> "AuthContext":
        """Optional SignedRequestAdapter path for capable headless clients
        (NOT the required baseline - see transport_reality_2026_08_22).

        `method` (revision 5, chatgpt seq206 finding #5): the MCP/tool
        method this signed request authorizes, bound into the canonical
        envelope - see canonical_envelope's docstring. A genuinely valid
        signature resubmitted under a different method fails verification.

        Verification precedence (revision 3, chatgpt seq195 - resolves the
        case 3 vs case 15 ambiguity that revision 2 left open):
          1. Compare hash_payload(payload) - the bytes ACTUALLY RECEIVED -
             against payload_hash_claim - the hash DECLARED inside the
             envelope that was signed. Mismatch -> PayloadTampered,
             regardless of whether the signature would otherwise verify.
          2. Only once they match, reconstruct
             canonical_envelope(..., method=method,
             payload_hash=payload_hash_claim) and verify the signature
             against it. Failure here -> InvalidCredential.
        This ordering means "the payload isn't what was signed" and "this
        wasn't signed by the right key (or the right method)" are always
        distinguishable, instead of collapsing into one ambiguous
        verification failure.

        Revision 4 (GREEN) fills in the rest of the precedence, chosen but
        left unspecified by revision 3 since no case in the matrix pins the
        relative order (each test isolates exactly one failure mode):
          3. Clock skew (case 11) - cheap, stateless, checked right after
             authenticity is established.
          4. Replay (case 4) - the nonce is burned here, immediately once
             the signature is confirmed authentic, regardless of what any
             later check decides. This stops an attacker from probing the
             same captured signed envelope for different rejection reasons
             by resubmitting it. Since revision 5, "seen"/"mark" go through
             the injected ReplayStore (see module docstring Revision 5
             note #3), not a private instance dict.
          5. agent_number_claim MEMBERSHIP (cases 2/12) - safe to trust now
             that the signature has authenticated it (see
             canonical_envelope's docstring). Revision 5: changed from a
             single-owner check to a membership check - see module
             docstring Revision 5 note #1.
          6. Revocation (case 5) - see the module docstring's Revision 4
             note for why this is a plain "has this principal EVER been
             revoked" check here, unlike the epoch-pinned comparison
             verify_bearer_token uses.

        On success, AuthContext.scopes is resolved LIVE from the registry
        (revision 5, finding #4) - not cached anywhere on this AuthStore.

        Raises InvalidCredential / PayloadTampered / ClockSkewExceeded /
        ReplayedRequest / AgentNumberMismatch / UnknownAgentNumber /
        PrincipalRevoked as appropriate.
        """
        # 1. Tamper check, before anything else (chatgpt seq195).
        if hash_payload(payload) != payload_hash_claim:
            raise PayloadTampered("received payload does not match payload_hash_claim")

        # 2-3. Signature verification, now including method (revision 5).
        # An unregistered principal_id fails closed as InvalidCredential
        # rather than leaking existence.
        try:
            credential = self._registry.credential_for(principal_id)
        except KeyError:
            raise InvalidCredential(f"no credential registered for {principal_id!r}") from None

        if self._verifier is None:
            raise RuntimeError("AuthStore has no SignatureVerifier configured for verify_signed_request")

        envelope = canonical_envelope(
            principal_id=principal_id,
            agent_number=agent_number_claim,
            method=method,
            timestamp=timestamp,
            request_id=request_id,
            payload_hash=payload_hash_claim,
        )
        if not self._verifier.verify(envelope, signature, credential):
            raise InvalidCredential(f"signature does not verify for {principal_id!r}")

        # 4. Clock skew, boundary inclusive.
        if abs(now - timestamp) > ALLOWED_CLOCK_SKEW_SECONDS:
            raise ClockSkewExceeded(f"timestamp {timestamp} outside {ALLOWED_CLOCK_SKEW_SECONDS}s of now={now}")

        # 5. Replay - opportunistically prune expired entries, then burn
        # this nonce now that it is authenticated, before any check below
        # that might still reject the request for other reasons. Goes
        # through the injected ReplayStore (revision 5).
        self._replay_store.prune(now, REPLAY_WINDOW_SECONDS)
        if self._replay_store.seen(principal_id, request_id, now, REPLAY_WINDOW_SECONDS):
            raise ReplayedRequest(f"request_id {request_id!r} already used by {principal_id!r}")
        self._replay_store.mark(principal_id, request_id, now)

        # 6. agent_number_claim MEMBERSHIP - trustworthy now that the
        # signature above has authenticated it. Revision 5: changed from a
        # single-owner check to a membership check (see PrincipalRegistry
        # Revision 5 note #1) - an agent_number may legitimately have
        # several bound principals.
        members = self._registry.agent_number_members(agent_number_claim)
        if not members:
            raise UnknownAgentNumber(f"agent_number {agent_number_claim!r} has no registered principals")
        if principal_id not in members:
            raise AgentNumberMismatch(
                f"principal {principal_id!r} is not bound to agent_number {agent_number_claim!r}"
            )

        # 7. Revocation - signed requests have no stored issuance epoch to
        # pin against (see module docstring); any revocation at all voids
        # every future signed request from this principal.
        current_epoch = self._registry.current_revocation_epoch(principal_id)
        if current_epoch != 0:
            raise PrincipalRevoked(f"principal {principal_id!r} has been revoked")

        return AuthContext(
            principal_id=principal_id,
            agent_number=agent_number_claim,
            principal_type=self._registry.principal_type_for(principal_id),
            revocation_epoch=current_epoch,
            authenticated_at=now,
            scopes=self._registry.scopes_for(principal_id),
            auth_method="signed_request",
        )

def require_identity_match(claimed_agent_id: str, auth_context: "AuthContext") -> None:
    """Case 17. Raises IdentityMismatch if claimed_agent_id does not match
    auth_context.agent_number exactly. Call this at every mutation boundary
    that also reads a client-supplied agent_id/from_agent body field - the
    body value may be logged/displayed but must never substitute for
    auth_context."""
    if claimed_agent_id != auth_context.agent_number:
        raise IdentityMismatch(
            f"body claimed agent_id {claimed_agent_id!r}, "
            f"authenticated caller is {auth_context.agent_number!r}"
        )


class ConnectorBinding:
    """Case 18. A trusted_connector principal (e.g. the ChatGPT tunnel-client
    process) authenticates itself at the transport level via its own local
    service credential - that proves ONLY connector identity. This binding
    is the explicit, registered list of agent_number(s)/principal_id(s) the
    connector is allowed to relay requests for."""

    def __init__(self) -> None:
        self._bindings: dict[str, set[str]] = {}

    def bind(self, connector_principal_id: str, allowed_agent_numbers: "set[str]") -> None:
        self._bindings[connector_principal_id] = set(allowed_agent_numbers)

    def verify_claim(self, connector_principal_id: str, claimed_agent_number: str) -> None:
        """Raises UnregisteredConnectorClaim if claimed_agent_number is not
        in this connector's bound set."""
        allowed = self._bindings.get(connector_principal_id, set())
        if claimed_agent_number not in allowed:
            raise UnregisteredConnectorClaim(
                f"connector {connector_principal_id!r} is not bound to agent_number {claimed_agent_number!r}"
            )
