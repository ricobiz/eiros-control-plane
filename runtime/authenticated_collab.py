from __future__ import annotations

from runtime.agent_auth import AuthContext, IdentityMismatch


class AuthenticatedCollab:
    """Authentication boundary for the first collaboration mutation slice.

    Slice 1 covers durable dialogue send/claim/ack/release and project-state
    writes only. Bootstrap/register/heartbeat/operator/control are separate
    authority domains and require explicit scopes in later slices.

    Delivery-plane wake/Pulse/SAM mutators are tracked as slice 1.5 and must be
    classified/authenticated before the global activation gate can turn green.
    VPS/file/queue/media tools are intentionally outside this facade because
    they are separate authority domains, not silently considered authenticated
    collaboration mutations.
    """

    def __init__(self, engine):
        self._engine = engine

    def send_message(self, auth: AuthContext, *args, **kwargs):
        raise NotImplementedError

    def inbox(self, auth: AuthContext, *args, **kwargs):
        raise NotImplementedError

    def acknowledge(self, auth: AuthContext, *args, **kwargs):
        raise NotImplementedError

    def release(self, auth: AuthContext, *args, **kwargs):
        raise NotImplementedError

    def set_project(self, auth: AuthContext, *args, **kwargs):
        raise NotImplementedError
