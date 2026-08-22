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
"""
from __future__ import annotations

import hashlib
import hmac

import pytest

from runtime.agent_auth import (
    ALLOWED_CLOCK_SKEW_SECONDS,
    AgentNumberMismatch,
    AuthContext,
    AuthStore,
    ClockSkewExceeded,
    ConnectorBinding,
    IdentityMismatch,
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

CREDENTIAL_A = b"real-secret-key-for-principal-a"
CREDENTIAL_B = b"real-secret-key-for-principal-b"
WRONG_CREDENTIAL = b"totally-different-key-registered-to-nobody"


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
) -> "PrincipalRegistry":
    registry = PrincipalRegistry()
    registry.register_principal(principal_id, agent_number, principal_type, credential)
    return registry


def _signed_request_kwargs(
    *,
    principal_id: str,
    agent_number_claim: str,
    credential: bytes,
    timestamp: float = NOW,
    request_id: str,
    payload: bytes,
) -> dict:
    """Builds a genuinely self-consistent, correctly-signed request:
    signs a real canonical envelope (which embeds payload's own hash as
    the declared payload_hash_claim) with a real HMAC over the given
    credential. Callers wanting a tampered fixture should mutate the
    returned dict's "payload" key afterward - "payload_hash_claim" stays
    as what was actually signed, exactly like a real tamper-in-transit."""
    payload_hash_claim = hash_payload(payload)
    envelope = canonical_envelope(
        principal_id=principal_id,
        agent_number=agent_number_claim,
        timestamp=timestamp,
        request_id=request_id,
        payload_hash=payload_hash_claim,
    )
    signature = _DeterministicTestSigner().sign(envelope, credential)
    return dict(
        principal_id=principal_id,
        agent_number_claim=agent_number_claim,
        payload=payload,
        payload_hash_claim=payload_hash_claim,
        signature=signature,
        timestamp=timestamp,
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
        timestamp=NOW,
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
        timestamp=NOW,
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
