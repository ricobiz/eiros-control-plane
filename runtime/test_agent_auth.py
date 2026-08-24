"""Negative-test matrix for runtime/agent_auth.py - pure auth-domain cases.

Covers threat_model_matrix_v1 cases 1-6, 11-12, 15-18 (project_state,
eiros-hub). Lease/generation-fencing cases (7-10, 13) and the watchdog
credential-file case (14) are out of scope here - those are the
complementary test_authenticated_collab.py / lease-primitive slice
(chatgpt, cycle 2).

STATUS 2026-08-22: this file is expected to be fully RED right now.
runtime/agent_auth.py is a tests-only contract skeleton - every method,
including AuthStore.__init__ and PrincipalRegistry.register_principal,
raises NotImplementedError. So every test below currently fails with a
NotImplementedError traceback pointing at the specific unimplemented
method, not an assertion failure and not an ImportError.

Revision 2: amended per chatgpt's independent review (seq193) of the
first RED SHA 0f0056d. Cases 3/4/5/11/12/15 now use a deterministic
test-only HMAC-SHA256 signer over a real canonical envelope instead of
arbitrary placeholder signature bytes. Case 2 redesigned to isolate
"claimed agent_number belongs to nobody" from case 12's "claimed
agent_number belongs to a different real principal".

Revision 3: amended per chatgpt's seq195 design decision resolving the
case 3 vs case 15 precedence question left open in revision 2.
verify_signed_request now takes an explicit payload_hash_claim (the hash
declared inside the signed envelope) separate from payload (the bytes
actually submitted). test_case15 now signs a real payload, then swaps in
different payload bytes while keeping the ORIGINAL payload_hash_claim -
exactly what a real tamper-in-transit looks like: the attacker can change
payload bytes, but cannot forge a new payload_hash_claim without
invalidating the signature over it.

Revision 4 (GREEN, 2026-08-23, claude): all 15 cases above pass for real
now (0f0056d/753d3f7 was RED-only against a NotImplementedError skeleton;
7e70a7a is the first real GREEN). No test bodies changed - the contract
these tests pin did not change, only agent_auth.py's implementation.

Revision 5 (2026-08-23, claude): ten new regression tests added per
chatgpt's seq206 (operative consolidated review, superseding an
overlapping seq205) + seq207 (correction to seq205 item 4) independent
execution-based review of GREEN SHA 7e70a7ae4b93eda18c665a5535f5f895a5dba833.
All ten were confirmed RED against that exact SHA before agent_auth.py was
changed - see the dialog_send report for the captured RED output. Covers
six real defects:

  (1) agent_number reverse-lookup was single-owner, silently displacing a
      second legitimate principal instead of the approved
      multi-principal-per-agent_number model. NOTE: seq205 (superseded)
      initially recommended the OPPOSITE - rejecting duplicate
      agent_number registration outright; seq207 explicitly corrected
      this as wrong and it was NOT implemented.
  (2) revocation was bypassable by minting a bearer token for an
      already-revoked principal, and by re-registering an already-revoked
      principal_id (which silently reset revocation_epoch back to 0).
  (3) the replay-request cache was private per-AuthStore-instance state
      with no shared/restart-safe backend.
  (4) AuthContext.scopes was structurally present but never populated by
      any code path.
  (5) canonical_envelope() did not bind the MCP/tool method, making a
      signature transferable across different method calls sharing the
      same payload/timestamp/request_id/identity.
  (6) the pipe-delimited envelope encoding was ambiguous across field
      boundaries - a real byte-for-byte collision reproduced and fixed via
      length-prefixed fields.
"""
from __future__ import annotations

import hashlib
import hmac
import threading

import pytest

from runtime.agent_auth import (
    ALLOWED_CLOCK_SKEW_SECONDS,
    AgentNumberMismatch,
    AuthContext,
    AuthStore,
    ClockSkewExceeded,
    ConflictingPrincipalRegistration,
    ConnectorBinding,
    IdentityMismatch,
    InMemoryReplayStore,
    InvalidCredential,
    NoAuthProvided,
    PayloadTampered,
    PrincipalRegistry,
    PrincipalRevoked,
    PrincipalType,
    ReplayedRequest,
    TokenExpired,
    UnknownAgentNumber,
    UnregisteredConnectorClaim,
    canonical_envelope,
    hash_payload,
    require_identity_match,
)

NOW = 1_800_000_000.0
NOW_MS = int(NOW * 1000)

CREDENTIAL_A = b"real-secret-key-for-principal-a"
CREDENTIAL_B = b"real-secret-key-for-principal-b"
CREDENTIAL_C = b"real-secret-key-for-principal-c"
WRONG_CREDENTIAL = b"totally-different-key-registered-to-nobody"

DEFAULT_METHOD = "collab.default_op"


class _DeterministicTestSigner:
    """Test-only HMAC-SHA256 signer/verifier - NOT the product's eventual
    asymmetric scheme. Exists so these pure-domain tests exercise real
    binding/replay/tamper/wrong-key semantics instead of asserting against
    arbitrary placeholder signature bytes that could never actually
    verify. Injected into AuthStore via its `verifier` constructor
    parameter - product code injects a real asymmetric verifier at the
    same call site (chatgpt seq193 review, adopted as-is)."""

    def sign(self, envelope: bytes, credential: bytes) -> bytes:
        return hmac.new(credential, envelope, hashlib.sha256).digest()

    def verify(self, envelope: bytes, signature: bytes, credential: bytes) -> bool:
        expected = hmac.new(credential, envelope, hashlib.sha256).digest()
        return hmac.compare_digest(expected, signature)


def _registry_with_one_principal(
    principal_id: str = "principal-a",
    agent_number: str = "AGN-0001",
    principal_type: "PrincipalType" = PrincipalType.INTERACTIVE_INSTALLATION,
    credential: bytes = CREDENTIAL_A,
    scopes: "frozenset[str]" = frozenset(),
) -> "PrincipalRegistry":
    registry = PrincipalRegistry()
    registry.register_principal(principal_id, agent_number, principal_type, credential, scopes)
    return registry


def _signed_request_kwargs(
    *,
    principal_id: str,
    agent_number_claim: str,
    credential: bytes,
    timestamp_ms: int = NOW_MS,
    request_id: str,
    payload: bytes,
    method: str = DEFAULT_METHOD,
) -> dict:
    """Builds a genuinely self-consistent, correctly-signed request:
    signs a real canonical envelope (which embeds payload's own hash as
    the declared payload_hash_claim, and - since revision 5 - the method
    this envelope authorizes) with a real HMAC over the given credential.
    Callers wanting a tampered fixture should mutate the returned dict's
    "payload" (or, since revision 5, "method") key afterward -
    "payload_hash_claim" stays as what was actually signed, exactly like a
    real tamper-in-transit. Revision 6: timestamp is now an explicit int
    timestamp_ms (milliseconds), not a float seconds value - see
    canonical_envelope's Revision 6 docstring note."""
    payload_hash_claim = hash_payload(payload)
    envelope = canonical_envelope(
        principal_id=principal_id,
        agent_number=agent_number_claim,
        method=method,
        timestamp_ms=timestamp_ms,
        request_id=request_id,
        payload_hash=payload_hash_claim,
    )
    signature = _DeterministicTestSigner().sign(envelope, credential)
    return dict(
        principal_id=principal_id,
        agent_number_claim=agent_number_claim,
        method=method,
        payload=payload,
        payload_hash_claim=payload_hash_claim,
        signature=signature,
        timestamp_ms=timestamp_ms,
        request_id=request_id,
    )


def _store(registry: "PrincipalRegistry") -> AuthStore:
    return AuthStore(registry, verifier=_DeterministicTestSigner())


# --- Case 1: no auth at all -------------------------------------------------

def test_case1_no_auth_provided_is_rejected():
    store = _store(_registry_with_one_principal())
    with pytest.raises(NoAuthProvided):
        store.verify_bearer_token(None, now=NOW)


# --- Case 2: forged agent_number - claims a number NOBODY owns -------------
# Isolated from case 12: principal-a's own credential and signature are
# genuinely valid, the ONLY problem is that the claimed number has no
# registered owner at all.

def test_case2_forged_agent_number_belonging_to_nobody_is_rejected():
    registry = _registry_with_one_principal(agent_number="AGN-0001")
    store = _store(registry)
    kwargs = _signed_request_kwargs(
        principal_id="principal-a",
        agent_number_claim="AGN-9999-nobody-owns-this",
        credential=CREDENTIAL_A,
        request_id="req-1",
        payload=b"do-the-thing",
    )
    with pytest.raises(UnknownAgentNumber):
        store.verify_signed_request(now=NOW, **kwargs)


# --- Case 3: wrong principal key/credential ---------------------------------
# payload_hash_claim genuinely matches payload (no tampering) - only the
# signature itself is wrong, isolating InvalidCredential from PayloadTampered.

def test_case3_wrong_principal_credential_is_rejected():
    registry = _registry_with_one_principal(agent_number="AGN-0001", credential=CREDENTIAL_A)
    store = _store(registry)
    kwargs = _signed_request_kwargs(
        principal_id="principal-a",
        agent_number_claim="AGN-0001",
        credential=WRONG_CREDENTIAL,  # signed with the wrong key
        request_id="req-2",
        payload=b"do-the-thing",
    )
    with pytest.raises(InvalidCredential):
        store.verify_signed_request(now=NOW, **kwargs)


# --- Case 4: replayed signed request / replayed request_id -----------------

def test_case4_replayed_request_id_is_rejected_on_second_use():
    registry = _registry_with_one_principal(agent_number="AGN-0001", credential=CREDENTIAL_A)
    store = _store(registry)
    kwargs = _signed_request_kwargs(
        principal_id="principal-a",
        agent_number_claim="AGN-0001",
        credential=CREDENTIAL_A,
        request_id="req-3-used-twice",
        payload=b"do-the-thing-once",
    )
    # First use must succeed (positive control, genuinely valid signature)
    # before the second use is exercised as the actual case-4 assertion.
    store.verify_signed_request(now=NOW, **kwargs)
    with pytest.raises(ReplayedRequest):
        store.verify_signed_request(now=NOW + 1, **kwargs)


# --- Case 5: revoked principal via the signature path -----------------------
# Everything about the request is otherwise legitimate (right key, right
# number, right signature, untampered payload) - only revocation should
# cause the rejection.

def test_case5_revoked_principal_rejected_via_signature_path():
    registry = _registry_with_one_principal(agent_number="AGN-0001", credential=CREDENTIAL_A)
    registry.revoke_principal("principal-a")
    store = _store(registry)
    kwargs = _signed_request_kwargs(
        principal_id="principal-a",
        agent_number_claim="AGN-0001",
        credential=CREDENTIAL_A,
        request_id="req-4",
        payload=b"do-the-thing",
    )
    with pytest.raises(PrincipalRevoked):
        store.verify_signed_request(now=NOW, **kwargs)


# --- Case 6: revoked principal via a still-unexpired CACHED bearer token ---
# The critical revocation-propagation-latency case: TTL alone must not be
# trusted once revocation_epoch has moved past what the token was issued
# against.

def test_case6_revoked_principal_rejected_even_with_unexpired_cached_token():
    registry = _registry_with_one_principal()
    store = _store(registry)
    token = store.issue_bearer_token("principal-a", ttl_seconds=3600.0, now=NOW)
    registry.revoke_principal("principal-a")
    # Still well within the token's TTL window - only revocation_epoch changed.
    with pytest.raises(PrincipalRevoked):
        store.verify_bearer_token(token.token, now=NOW + 5.0)


# --- Case 11: clock-skew boundary, exercised exactly at the edge -----------

def test_case11_clock_skew_exactly_at_boundary_is_accepted_not_rejected():
    registry = _registry_with_one_principal(agent_number="AGN-0001", credential=CREDENTIAL_A)
    store = _store(registry)
    kwargs = _signed_request_kwargs(
        principal_id="principal-a",
        agent_number_claim="AGN-0001",
        credential=CREDENTIAL_A,
        timestamp_ms=NOW_MS,
        request_id="req-5-boundary",
        payload=b"do-the-thing",
    )
    # Should simply not raise - positive control at the accepted boundary.
    store.verify_signed_request(now=NOW + ALLOWED_CLOCK_SKEW_SECONDS, **kwargs)


def test_case11_clock_skew_one_second_past_boundary_is_rejected():
    registry = _registry_with_one_principal(agent_number="AGN-0001", credential=CREDENTIAL_A)
    store = _store(registry)
    kwargs = _signed_request_kwargs(
        principal_id="principal-a",
        agent_number_claim="AGN-0001",
        credential=CREDENTIAL_A,
        timestamp_ms=NOW_MS,
        request_id="req-6-past-boundary",
        payload=b"do-the-thing",
    )
    with pytest.raises(ClockSkewExceeded):
        store.verify_signed_request(now=NOW + ALLOWED_CLOCK_SKEW_SECONDS + 1.0, **kwargs)


# --- Case 12: cross-agent_number substitution -------------------------------
# principal-a's signature is genuinely valid FOR principal-a, but claims
# AGN-0002 - a number that IS registered, just to principal-b, not
# principal-a. Distinct from case 2 (claimed number belongs to nobody).

def test_case12_cross_agent_number_substitution_is_rejected():
    registry = _registry_with_one_principal(
        principal_id="principal-a", agent_number="AGN-0001", credential=CREDENTIAL_A
    )
    registry.register_principal("principal-b", "AGN-0002", PrincipalType.INTERACTIVE_INSTALLATION, CREDENTIAL_B)
    store = _store(registry)
    kwargs = _signed_request_kwargs(
        principal_id="principal-a",
        agent_number_claim="AGN-0002",  # real number, but it's principal-b's
        credential=CREDENTIAL_A,  # principal-a's own, genuinely valid key
        request_id="req-7",
        payload=b"do-the-thing",
    )
    with pytest.raises(AgentNumberMismatch):
        store.verify_signed_request(now=NOW, **kwargs)


# --- Case 15: valid signature but tampered payload --------------------------
# Real HMAC signature over a REAL envelope (whose payload_hash_claim is the
# ORIGINAL payload's hash) - then the actually-submitted payload is swapped.
# hash_payload(submitted payload) != payload_hash_claim, so this must be
# rejected BEFORE signature verification even runs (chatgpt seq195 order).

def test_case15_tampered_payload_is_rejected_even_with_valid_signature():
    registry = _registry_with_one_principal(agent_number="AGN-0001", credential=CREDENTIAL_A)
    store = _store(registry)
    kwargs = _signed_request_kwargs(
        principal_id="principal-a",
        agent_number_claim="AGN-0001",
        credential=CREDENTIAL_A,
        request_id="req-8",
        payload=b"original-payload-that-was-actually-signed",
    )
    # Swap the ACTUAL payload after signing. payload_hash_claim is left
    # untouched - it's still the hash of the ORIGINAL payload, exactly
    # like a genuine tamper-in-transit (attacker can't forge a new claim
    # without invalidating the signature that covers it).
    kwargs["payload"] = b"mutated-after-signing-different-bytes"
    with pytest.raises(PayloadTampered):
        store.verify_signed_request(now=NOW, **kwargs)


# --- Case 16: expired bearer/session token used past TTL -------------------

def test_case16_expired_bearer_token_is_rejected():
    registry = _registry_with_one_principal()
    store = _store(registry)
    token = store.issue_bearer_token("principal-a", ttl_seconds=60.0, now=NOW)
    with pytest.raises(TokenExpired):
        store.verify_bearer_token(token.token, now=NOW + 61.0)


def test_case16_expired_is_distinct_from_revoked_same_principal_never_revoked():
    """Guards against collapsing TokenExpired and PrincipalRevoked into one
    code path - this principal is never revoked, only its token ages out."""
    registry = _registry_with_one_principal()
    store = _store(registry)
    token = store.issue_bearer_token("principal-a", ttl_seconds=60.0, now=NOW)
    with pytest.raises(TokenExpired):
        store.verify_bearer_token(token.token, now=NOW + 61.0)
    # revocation_epoch must be unchanged - nothing revoked this principal.
    assert registry.current_revocation_epoch("principal-a") == 0


# --- Case 17: agent_id/from_agent body field mismatched vs AuthContext -----

def test_case17_body_identity_mismatch_against_auth_context_is_rejected():
    auth_context = AuthContext(
        principal_id="principal-a",
        agent_number="AGN-0001",
        principal_type=PrincipalType.INTERACTIVE_INSTALLATION,
        revocation_epoch=0,
        authenticated_at=NOW,
    )
    with pytest.raises(IdentityMismatch):
        require_identity_match("AGN-0002-claimed-in-body", auth_context)


# --- Case 18: connector auth succeeds but claims an unregistered principal -

def test_case18_connector_claims_unregistered_agent_number_is_rejected():
    binding = ConnectorBinding()
    binding.bind("chatgpt-tunnel-connector", {"AGN-0001", "AGN-0002"})
    with pytest.raises(UnregisteredConnectorClaim):
        binding.verify_claim("chatgpt-tunnel-connector", "AGN-9999-not-bound")


def test_case18_connector_claims_registered_agent_number_is_accepted():
    binding = ConnectorBinding()
    binding.bind("chatgpt-tunnel-connector", {"AGN-0001", "AGN-0002"})
    # Should simply not raise - no assertion beyond that, matching
    # verify_claim's documented contract (raises only on an unbound claim).
    binding.verify_claim("chatgpt-tunnel-connector", "AGN-0001")


# --- Subscriber identity reconciliation: public number cardinality ----------
# Product correction (Rico, 2026-08-24): one public callable number identifies
# exactly one user x platform x device/installation subscriber. Independent
# principals do not coexist behind that public address; service principals are
# non-dialable infrastructure identities.

def test_second_independent_installation_cannot_share_public_subscriber_number():
    registry = PrincipalRegistry()
    registry.register_principal(
        "principal-phone-a",
        "SUB-DEVICE-A",
        PrincipalType.INTERACTIVE_INSTALLATION,
        CREDENTIAL_A,
    )

    # RED against c0b38ab: its reverse index intentionally accepts this and
    # turns SUB-DEVICE-A into a set-of-principals. The revised product model
    # requires a distinct public number for the second installation instead.
    with pytest.raises(ConflictingPrincipalRegistration):
        registry.register_principal(
            "principal-phone-b",
            "SUB-DEVICE-A",
            PrincipalType.INTERACTIVE_INSTALLATION,
            CREDENTIAL_B,
        )


def test_service_auth_context_has_no_public_subscriber_number():
    registry = PrincipalRegistry()
    registry.register_principal(
        "worker-1",
        "",
        PrincipalType.HEADLESS_SERVICE,
        CREDENTIAL_B,
        scopes=frozenset({"internal:work"}),
    )
    store = _store(registry)
    token = store.issue_bearer_token("worker-1", ttl_seconds=60.0, now=NOW)
    ctx = store.verify_bearer_token(token.token, now=NOW + 1.0)

    # RED against c0b38ab: AuthContext currently overloads agent_number for
    # every principal type. The revised typed context exposes no callable
    # SubscriberNumber for a service principal.
    assert ctx.subscriber_number is None


def test_case12_still_rejected_for_cross_subscriber_substitution():
    """A valid Subscriber A credential must not authorize Subscriber B."""
    registry = PrincipalRegistry()
    registry.register_principal(
        "principal-a",
        "SUB-A",
        PrincipalType.INTERACTIVE_INSTALLATION,
        CREDENTIAL_A,
    )
    registry.register_principal(
        "principal-b",
        "SUB-B",
        PrincipalType.INTERACTIVE_INSTALLATION,
        CREDENTIAL_B,
    )
    store = _store(registry)
    kwargs = _signed_request_kwargs(
        principal_id="principal-b",
        agent_number_claim="SUB-A",  # real public subscriber, wrong principal
        credential=CREDENTIAL_B,
        request_id="req-cross-subscriber",
        payload=b"do-the-thing",
    )
    with pytest.raises(AgentNumberMismatch):
        store.verify_signed_request(now=NOW, **kwargs)


# --- Revision 5: chatgpt seq206 finding #2 ----------------------------------
# Revocation must not be bypassable either by minting a fresh token after
# revoke, or by simply re-registering the same principal_id.

def test_revoked_principal_cannot_be_issued_a_new_bearer_token():
    registry = _registry_with_one_principal()
    registry.revoke_principal("principal-a")
    store = _store(registry)
    with pytest.raises(PrincipalRevoked):
        store.issue_bearer_token("principal-a", ttl_seconds=3600.0, now=NOW)


def test_re_registering_same_principal_id_does_not_reset_revocation_epoch():
    registry = _registry_with_one_principal(agent_number="AGN-0001", credential=CREDENTIAL_A)
    registry.revoke_principal("principal-a")
    assert registry.current_revocation_epoch("principal-a") == 1
    # Re-registering with the exact same data must be a no-op, not a reset.
    registry.register_principal("principal-a", "AGN-0001", PrincipalType.INTERACTIVE_INSTALLATION, CREDENTIAL_A)
    assert registry.current_revocation_epoch("principal-a") == 1


def test_re_registering_same_principal_id_with_different_data_is_rejected():
    """Companion to the above: a re-registration attempt that actually
    CHANGES bound data (here, a different credential) must be rejected
    outright, not silently accepted as if it were a legitimate rebind."""
    registry = _registry_with_one_principal(agent_number="AGN-0001", credential=CREDENTIAL_A)
    with pytest.raises(ConflictingPrincipalRegistration):
        registry.register_principal("principal-a", "AGN-0001", PrincipalType.INTERACTIVE_INSTALLATION, CREDENTIAL_B)


# --- Revision 5: chatgpt seq206 finding #3 ----------------------------------
# Replay protection must survive AuthStore reconstruction when the same
# ReplayStore instance is shared.

def test_replay_protection_survives_a_new_authstore_instance_sharing_the_replay_store():
    registry = _registry_with_one_principal(agent_number="AGN-0001", credential=CREDENTIAL_A)
    shared_replay_store = InMemoryReplayStore()
    store1 = AuthStore(registry, verifier=_DeterministicTestSigner(), replay_store=shared_replay_store)
    kwargs = _signed_request_kwargs(
        principal_id="principal-a",
        agent_number_claim="AGN-0001",
        credential=CREDENTIAL_A,
        request_id="req-shared-replay",
        payload=b"do-the-thing",
    )
    store1.verify_signed_request(now=NOW, **kwargs)

    # A second, freshly-constructed AuthStore sharing the SAME replay
    # store must see req-shared-replay as already used.
    store2 = AuthStore(registry, verifier=_DeterministicTestSigner(), replay_store=shared_replay_store)
    with pytest.raises(ReplayedRequest):
        store2.verify_signed_request(now=NOW + 1, **kwargs)


# --- Revision 5: chatgpt seq206 finding #4 ----------------------------------
# Scopes must actually survive verification: live-resolved for signed
# requests, baked in at issuance for bearer tokens.

def test_signed_request_scopes_are_populated_live_from_the_registry():
    registry = _registry_with_one_principal(
        agent_number="AGN-0001", credential=CREDENTIAL_A, scopes=frozenset({"collab", "bootstrap"})
    )
    store = _store(registry)
    kwargs = _signed_request_kwargs(
        principal_id="principal-a",
        agent_number_claim="AGN-0001",
        credential=CREDENTIAL_A,
        request_id="req-scopes-signed",
        payload=b"do-the-thing",
    )
    ctx = store.verify_signed_request(now=NOW, **kwargs)
    assert ctx.scopes == frozenset({"collab", "bootstrap"})


def test_bearer_token_scopes_are_baked_in_at_issuance_not_re_read_live():
    registry = _registry_with_one_principal(scopes=frozenset({"collab"}))
    store = _store(registry)
    token = store.issue_bearer_token("principal-a", ttl_seconds=3600.0, now=NOW)
    ctx = store.verify_bearer_token(token.token, now=NOW + 1.0)
    assert ctx.scopes == frozenset({"collab"})


# --- Revision 5: chatgpt seq206 findings #5 and #6 --------------------------
# canonical_envelope must bind method (no cross-method replay) and must be
# unambiguous across field boundaries (no delimiter-collision forgery).

def test_canonical_envelope_binds_method_so_cross_method_replay_is_rejected():
    registry = _registry_with_one_principal(agent_number="AGN-0001", credential=CREDENTIAL_A)
    store = _store(registry)
    kwargs = _signed_request_kwargs(
        principal_id="principal-a",
        agent_number_claim="AGN-0001",
        credential=CREDENTIAL_A,
        method="collab.read_only_method",
        request_id="req-method-binding",
        payload=b"do-the-thing",
    )
    # Resubmit the SAME genuinely-signed envelope under a DIFFERENT method.
    kwargs["method"] = "collab.dangerous_mutating_method"
    with pytest.raises(InvalidCredential):
        store.verify_signed_request(now=NOW, **kwargs)


def test_canonical_envelope_is_unambiguous_across_field_boundaries():
    """The old pipe-delimited encoding let two DIFFERENT logical envelopes
    serialize to IDENTICAL bytes whenever a field itself contained the
    delimiter, making them mutually forgeable under the same signature.
    Length-prefixed encoding must keep these distinct."""
    env_a = canonical_envelope(
        principal_id="a|b", agent_number="c", method="m", timestamp_ms=1_000, request_id="d", payload_hash="e"
    )
    env_b = canonical_envelope(
        principal_id="a", agent_number="b|c", method="m", timestamp_ms=1_000, request_id="d", payload_hash="e"
    )
    assert env_a != env_b


# --- Revision 6 (2026-08-24): chatgpt seq209 finding #1 (REPLAY RACE) ------
# ReplayStore.seen()+mark() is a non-atomic check-then-mark pair. These two
# tests independently reproduce chatgpt's own adversarial finding BEFORE any
# fix is applied - they are expected to be genuinely RED against unmodified
# 127cb6c, run in isolation from the timestamp_ms fix below.


class _RaceForcingReplayStore:
    """Test double wrapping a real InMemoryReplayStore. If AuthStore still
    uses the old two-step seen()-then-mark() sequence, seen() blocks on a
    2-party barrier AFTER computing its answer but BEFORE returning, so two
    concurrent callers are GUARANTEED to both observe "not seen" before
    either has a chance to mark() - deterministically forcing the exact
    race window chatgpt's seq209 report describes, instead of depending on
    unreliable GIL-timing luck. consume_once() passes straight through to
    the real implementation unmodified: proving the FIX is race-free does
    not require forcing anything, since the real lock is what is under
    test there."""

    def __init__(self, inner: "InMemoryReplayStore") -> None:
        self._inner = inner
        self._barrier = threading.Barrier(2)

    def seen(self, principal_id, request_id, now, window_seconds) -> bool:
        result = self._inner.seen(principal_id, request_id, now, window_seconds)
        try:
            self._barrier.wait(timeout=5)
        except threading.BrokenBarrierError:
            pass
        return result

    def mark(self, principal_id, request_id, now) -> None:
        self._inner.mark(principal_id, request_id, now)

    def prune(self, now, window_seconds) -> None:
        self._inner.prune(now, window_seconds)

    def consume_once(self, principal_id, request_id, now, window_seconds) -> bool:
        return self._inner.consume_once(principal_id, request_id, now, window_seconds)


def test_consume_once_is_atomic_under_concurrent_callers():
    """Direct unit test of the atomic replay primitive chatgpt's seq209
    review asked for: many threads racing to consume the SAME
    (principal_id, request_id) key must yield exactly one True, regardless
    of scheduling. On unmodified 127cb6c, InMemoryReplayStore has no
    consume_once at all - this is expected to fail with AttributeError."""
    store = InMemoryReplayStore()
    n = 50
    start_barrier = threading.Barrier(n)
    results: list = [False] * n

    def worker(i: int) -> None:
        start_barrier.wait(timeout=5)
        results[i] = store.consume_once("principal-race", "req-race", now=NOW, window_seconds=600.0)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    winners = sum(1 for r in results if r)
    assert winners == 1, f"expected exactly one caller to win consume_once, got {winners} winners"


def test_concurrent_authstore_instances_do_not_both_accept_the_same_replay():
    """Reproduces chatgpt's seq209 finding directly: two AuthStore instances
    sharing one ReplayStore backend, both verifying the IDENTICAL
    genuinely-signed request at effectively the same instant, must not both
    succeed - exactly one must ACCEPT and the other must see ReplayedRequest.
    Forces the check-then-mark race window deterministically via
    _RaceForcingReplayStore so this test is reliable rather than depending
    on GIL-timing luck. On unmodified 127cb6c this reproduces chatgpt's
    exact result: both threads ACCEPT."""
    registry = _registry_with_one_principal(agent_number="AGN-0001", credential=CREDENTIAL_A)
    shared_backend = InMemoryReplayStore()
    racing_store = _RaceForcingReplayStore(shared_backend)
    store_a = AuthStore(registry, verifier=_DeterministicTestSigner(), replay_store=racing_store)
    store_b = AuthStore(registry, verifier=_DeterministicTestSigner(), replay_store=racing_store)
    kwargs = _signed_request_kwargs(
        principal_id="principal-a",
        agent_number_claim="AGN-0001",
        credential=CREDENTIAL_A,
        request_id="req-concurrent-replay",
        payload=b"do-the-thing",
    )

    outcomes: list = []
    outcomes_lock = threading.Lock()

    def attempt(store: "AuthStore") -> None:
        try:
            store.verify_signed_request(now=NOW, **kwargs)
            outcome = "ACCEPT"
        except ReplayedRequest:
            outcome = "REJECTED"
        with outcomes_lock:
            outcomes.append(outcome)

    t1 = threading.Thread(target=attempt, args=(store_a,))
    t2 = threading.Thread(target=attempt, args=(store_b,))
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert sorted(outcomes) == ["ACCEPT", "REJECTED"], (
        f"expected exactly one ACCEPT and one REJECTED for a genuine concurrent "
        f"replay, got {outcomes}"
    )


# --- Revision 6 (2026-08-24): chatgpt seq209 finding #2 (TIMESTAMP) --------
# canonical_envelope's internal round(timestamp * 1000) is Python
# banker's-rounding, which disagrees with JS-style Math.round() at exact
# .5ms boundaries (independently confirmed: round(1000.5) == 1000, not
# 1001). The fix requires an explicit int timestamp_ms at the boundary -
# no rounding inside the signing function at all. Both tests below are
# expected to be genuinely RED against unmodified 127cb6c, since that
# signature has no timestamp_ms parameter at all yet.


def test_canonical_envelope_uses_explicit_timestamp_ms_with_no_internal_rounding():
    """The encoded bytes must be the EXACT decimal string of the given
    int, with no rounding step anywhere inside this function."""
    envelope = canonical_envelope(
        principal_id="p", agent_number="a", method="m",
        timestamp_ms=1_800_000_000_500, request_id="r", payload_hash="h",
    )
    assert str(1_800_000_000_500).encode("ascii") in envelope


def test_canonical_envelope_rejects_float_timestamp_ms():
    """A float must be rejected outright with a clear type error, not
    silently accepted and rounded - silent internal rounding is exactly
    the bug chatgpt's seq209 review found."""
    with pytest.raises(TypeError, match="int"):
        canonical_envelope(
            principal_id="p", agent_number="a", method="m",
            timestamp_ms=1000.0, request_id="r", payload_hash="h",
        )
