"""Transport-neutral caller-authentication domain for EIROS.

Pure domain module: no FastMCP/HTTP/stdio/tunnel imports here. Per-transport
adapters (Claude HTTP bearer/token_verifier, ChatGPT tunnel connector,
watchdog credential-file) live elsewhere and translate into calls on this
module's API. See project_state(eiros-hub).identity_and_auth_2026_08_22 and
.threat_model_matrix_v1 for the design this file implements the contract of.

STATUS: tests-only contract skeleton (cycle 2, 2026-08-22, claude). Every
function below raises NotImplementedError. No auth decision logic exists
yet - this file exists so runtime/test_agent_auth.py can import a stable
API and fail RED for the right reason (contract exists, not implemented)
instead of ImportError (contract itself is wrong-shaped).

Revision 2 (same day): amended per chatgpt's independent review (seq193,
dialog eiros-hub/first-contact) of the first tests-only SHA 0f0056d.
Changes in this revision, all still zero-behavior:
  - AuthContext gained `scopes` and `auth_method` fields - chatgpt's point:
    without scopes, bootstrap/register/operator/control cannot stay
    separate authorities from plain collab mutation once a facade tries
    to enforce them, since principal_type alone is too coarse.
  - Added SignatureVerifier (a typing.Protocol, no implementation) plus
    canonical_envelope()/hash_payload() pure data-transform helpers, so
    tests can inject a deterministic signer instead of asserting against
    arbitrary placeholder signature bytes that could never actually
    verify once real signing exists. AuthStore.__init__ now accepts an
    optional `verifier` to inject that backend - product code will inject
    a real asymmetric verifier at the same call site later.
  - OPEN DESIGN QUESTION, not resolved here (flagged to chatgpt, not
    quietly assumed): the exact mechanism by which a real implementation
    distinguishes InvalidCredential (case 3, wrong key) from
    PayloadTampered (case 15, right key, mismatched payload) at
    verification time. A naive single HMAC/signature check over a
    freshly-recomputed envelope cannot tell the two apart - it just
    fails once, either way. Resolving this (e.g. request-id-scoped
    envelope-hash pre-registration at issuance, or a detached declared-
    hash-plus-payload design) is real implementation work for the GREEN
    phase, not a test-authoring detail. test_agent_auth.py constructs
    both fixtures unambiguously (wrong key vs. right key/wrong payload)
    so whichever mechanism is chosen has a precise contract to satisfy.

Threat-matrix case numbers below match threat_model_matrix_v1 verbatim.
"""
from __future__ import annotations

import dataclasses
import enum
import hashlib
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
    at all (threat_model_matrix_v1's own wording). Must be distinguishable
    from AgentNumberMismatch (case 12): case 2 is "this number belongs to
    nobody"; case 12 is "this number belongs to someone else, and the
    caller's own credential is genuinely valid for a DIFFERENT number"."""


class InvalidCredential(AuthError):
    """Case 3: signature or bearer token does not match the claimed
    principal's own key/secret (wrong principal key/credential)."""


class ReplayedRequest(AuthError):
    """Case 4: request_id already seen within REPLAY_WINDOW_SECONDS."""


class PrincipalRevoked(AuthError):
    """Cases 5 and 6: the principal's CURRENT revocation_epoch is ahead of
    the epoch bound to the credential/token being verified. Must be checked
    fresh on every verification, including for an otherwise-still-valid
    cached bearer token (case 6) - never deferred to TTL expiry."""


class ClockSkewExceeded(AuthError):
    """Case 11: |now - request timestamp| > ALLOWED_CLOCK_SKEW_SECONDS.
    Boundary is inclusive: exactly ALLOWED_CLOCK_SKEW_SECONDS is accepted,
    any amount past it is rejected."""


class AgentNumberMismatch(AuthError):
    """Case 12: signature/token is genuinely valid for principal P, and P is
    bound to agent_number A, but the request payload claims agent_number B,
    where B is a real, registered number belonging to a DIFFERENT principal.
    See UnknownAgentNumber for the "B belongs to nobody" case (case 2)."""


class PayloadTampered(AuthError):
    """Case 15: the signature/token itself verifies for THIS principal's
    key, but the covered/declared payload does not match the payload bytes
    actually submitted alongside it (payload swapped after signing).
    Distinct from InvalidCredential (case 3): here the KEY is right, only
    the payload disagrees with what was signed. See this module's revision
    2 docstring note for the open question of how an implementation tells
    the two apart at verification time."""


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
    exception - single source of truth for the auth-domain error taxonomy."""


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
    higher-assurance-path enforcement.
    """

    principal_id: str
    agent_number: str
    principal_type: "PrincipalType"
    revocation_epoch: int
    authenticated_at: float
    scopes: "tuple[str, ...]" = ()
    auth_method: str = ""


@dataclasses.dataclass(frozen=True)
class BearerToken:
    """Minted after asymmetric principal-keypair proof; used for ongoing
    per-request auth on the Claude HTTP path (FastMCP token_verifier)."""

    token: str
    principal_id: str
    issued_epoch: int
    issued_at: float
    expires_at: float


class SignatureVerifier(typing.Protocol):
    """Pluggable signature backend, injected into AuthStore (revision 2).
    The product path injects a real asymmetric verifier; tests inject a
    deterministic HMAC-based one (see test_agent_auth.py). Purely
    structural typing - no implementation lives here, matching this
    file's tests-only-skeleton status."""

    def sign(self, envelope: bytes, credential: bytes) -> bytes: ...

    def verify(self, envelope: bytes, signature: bytes, credential: bytes) -> bool: ...


def hash_payload(payload: bytes) -> str:
    """Single canonical definition of "payload hash" - both test fixtures
    and any real implementation must use this, not hand-rolled hashing, so
    a signed envelope's declared hash is comparable to a freshly-received
    payload's hash. Pure data transform, not a decision."""
    return hashlib.sha256(payload).hexdigest()


def canonical_envelope(
    *,
    principal_id: str,
    agent_number: str,
    timestamp: float,
    request_id: str,
    payload_hash: str,
) -> bytes:
    """The exact bytes a SignatureVerifier signs/verifies over. Binds
    principal_id, agent_number, timestamp, request_id and the payload's
    hash together, so a signature cannot be silently replayed against a
    different payload, principal, or agent_number claim. Pure data
    transform - no crypto, no decision logic."""
    return f"{principal_id}|{agent_number}|{timestamp}|{request_id}|{payload_hash}".encode("utf-8")


class PrincipalRegistry:
    """Source of truth for registered principals: agent_number binding,
    principal_type, credential material, and current revocation_epoch.
    agent_number itself is server-assigned/opaque/high-entropy elsewhere
    (registration flow, not this module) - this registry only stores the
    resulting binding."""

    def register_principal(
        self,
        principal_id: str,
        agent_number: str,
        principal_type: "PrincipalType",
        credential: bytes,
    ) -> None:
        raise NotImplementedError

    def revoke_principal(self, principal_id: str) -> None:
        """Advances the principal's revocation_epoch by exactly one. Must be
        observed by the very next verification of ANY credential for this
        principal, including already-issued cached bearer tokens (case 6)."""
        raise NotImplementedError

    def current_revocation_epoch(self, principal_id: str) -> int:
        raise NotImplementedError

    def agent_number_for(self, principal_id: str) -> str:
        raise NotImplementedError

    def credential_for(self, principal_id: str) -> bytes:
        raise NotImplementedError

    def principal_for_agent_number(self, agent_number: str) -> "str | None":
        """Reverse lookup used to distinguish case 2 from case 12: returns
        None if nobody is registered under agent_number (case 2 territory),
        or the owning principal_id if somebody is (case 12 territory when
        that owner isn't the caller)."""
        raise NotImplementedError


class AuthStore:
    """Issues and verifies bearer tokens and signed requests against a
    PrincipalRegistry. Transport-neutral: adapters call in with whatever
    they received (header value, stdio payload field, ...) and get back an
    AuthContext, or an AuthError subclass is raised."""

    def __init__(self, registry: "PrincipalRegistry", *, verifier: "SignatureVerifier | None" = None) -> None:
        raise NotImplementedError

    def issue_bearer_token(self, principal_id: str, ttl_seconds: float, now: float) -> "BearerToken":
        raise NotImplementedError

    def verify_bearer_token(self, token: "str | None", now: float) -> "AuthContext":
        """Raises NoAuthProvided / UnknownAgentNumber / InvalidCredential /
        TokenExpired / PrincipalRevoked as appropriate, in that logical
        precedence (missing before malformed before expired before
        revoked-state, though revocation is ALWAYS re-checked regardless of
        which other checks already passed - see PrincipalRevoked)."""
        raise NotImplementedError

    def verify_signed_request(
        self,
        *,
        principal_id: str,
        agent_number_claim: str,
        payload: bytes,
        signature: bytes,
        timestamp: float,
        request_id: str,
        now: float,
    ) -> "AuthContext":
        """Optional SignedRequestAdapter path for capable headless clients
        (NOT the required baseline - see transport_reality_2026_08_22).
        Raises InvalidCredential / PayloadTampered / ClockSkewExceeded /
        ReplayedRequest / AgentNumberMismatch / UnknownAgentNumber /
        PrincipalRevoked as appropriate."""
        raise NotImplementedError


def require_identity_match(claimed_agent_id: str, auth_context: "AuthContext") -> None:
    """Case 17. Raises IdentityMismatch if claimed_agent_id does not match
    auth_context exactly. Call this at every mutation boundary that also
    reads a client-supplied agent_id/from_agent body field - the body value
    may be logged/displayed but must never substitute for auth_context."""
    raise NotImplementedError


class ConnectorBinding:
    """Case 18. A trusted_connector principal (e.g. the ChatGPT tunnel-client
    process) authenticates itself at the transport level via its own local
    service credential - that proves ONLY connector identity. This binding
    is the explicit, registered list of agent_number(s)/principal_id(s) the
    connector is allowed to relay requests for."""

    def bind(self, connector_principal_id: str, allowed_agent_numbers: "set[str]") -> None:
        raise NotImplementedError

    def verify_claim(self, connector_principal_id: str, claimed_agent_number: str) -> None:
        """Raises UnregisteredConnectorClaim if claimed_agent_number is not
        in this connector's bound set."""
        raise NotImplementedError
