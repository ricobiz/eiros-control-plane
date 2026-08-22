from __future__ import annotations


class AuthIdentityMismatch(RuntimeError):
    pass


class AuthenticatedCollab:
    def __init__(self, engine):
        self._engine = engine

    def send_message(self, *args, **kwargs):
        raise NotImplementedError

    def inbox(self, *args, **kwargs):
        raise NotImplementedError

    def acknowledge(self, *args, **kwargs):
        raise NotImplementedError

    def release(self, *args, **kwargs):
        raise NotImplementedError

    def set_project(self, *args, **kwargs):
        raise NotImplementedError
