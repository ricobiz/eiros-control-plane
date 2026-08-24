from __future__ import annotations

from typing import Any

from runtime.agent_auth import AuthContext, require_identity_match


class AuthenticatedCollab:
    """Authentication boundary for the first collaboration mutation slice.

    Slice 1 covers durable dialogue send/claim/ack/release and project-state
    writes only. The authenticated actor always comes from ``AuthContext``;
    any legacy body identity is treated only as an assertion and rejected on
    mismatch before the underlying collaboration engine is called.

    Bootstrap/register/heartbeat/operator/control are separate authority
    domains and require explicit scopes in later slices.

    Delivery-plane wake/Pulse/SAM mutators are tracked as slice 1.5 and must be
    classified/authenticated before the global activation gate can turn green.
    VPS/file/queue/media tools are intentionally outside this facade because
    they are separate authority domains, not silently considered authenticated
    collaboration mutations.
    """

    def __init__(self, engine: Any):
        self._engine = engine

    @staticmethod
    def _actor(auth: AuthContext, claimed_agent: str | None) -> str:
        """Return the server-authenticated actor after validating any body claim."""
        if claimed_agent is not None:
            require_identity_match(claimed_agent, auth)
        return auth.agent_number

    def send_message(
        self,
        auth: AuthContext,
        *,
        from_agent: str | None = None,
        to_agent: str,
        content: str,
        kind: str = "call",
        project_id: str = "default",
        thread_id: str = "main",
        scene_id: str = "",
        reply_to: str = "",
        expects_reply: bool = True,
        metadata: dict[str, Any] | None = None,
        idempotency_key: str = "",
    ):
        actor = self._actor(auth, from_agent)
        return self._engine.send_message(
            from_agent=actor,
            to_agent=to_agent,
            content=content,
            kind=kind,
            project_id=project_id,
            thread_id=thread_id,
            scene_id=scene_id,
            reply_to=reply_to,
            expects_reply=expects_reply,
            metadata=metadata,
            idempotency_key=idempotency_key,
        )

    def inbox(
        self,
        auth: AuthContext,
        *,
        agent_id: str | None = None,
        client_id: str,
        limit: int = 10,
        claim_seconds: int = 180,
        project_id: str = "",
        thread_id: str = "",
    ):
        actor = self._actor(auth, agent_id)
        return self._engine.inbox(
            actor,
            client_id,
            limit=limit,
            claim_seconds=claim_seconds,
            project_id=project_id,
            thread_id=thread_id,
        )

    def acknowledge(
        self,
        auth: AuthContext,
        *,
        agent_id: str | None = None,
        message_id: str,
        result: str = "",
    ):
        actor = self._actor(auth, agent_id)
        return self._engine.acknowledge(actor, message_id, result=result)

    def release(
        self,
        auth: AuthContext,
        *,
        agent_id: str | None = None,
        message_id: str,
        reason: str = "",
    ):
        actor = self._actor(auth, agent_id)
        return self._engine.release(actor, message_id, reason=reason)

    def set_project(
        self,
        auth: AuthContext,
        *,
        agent_id: str | None = None,
        project_id: str,
        state: dict[str, Any],
        expected_revision: int = -1,
    ):
        actor = self._actor(auth, agent_id)
        return self._engine.set_project(
            actor,
            project_id,
            state,
            expected_revision=expected_revision,
        )
