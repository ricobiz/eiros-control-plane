from __future__ import annotations

import shutil
from pathlib import Path
from typing import Sequence

from .runpod import AttemptState, RemoteAttempt, WorkerState, WorkerStatus


class FakeRunPodProvider:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.worker_state = WorkerState.RUNNING
        self.launch_count = 0
        self.stop_count = 0
        self.transport_unknown = False
        self.attempts: dict[tuple[str, str], RemoteAttempt] = {}

    def ensure_running(self) -> WorkerStatus:
        if self.worker_state is not WorkerState.RUNNING:
            self.worker_state = WorkerState.RUNNING
        return WorkerStatus(self.worker_state, 'fake:22')

    def inspect_attempt(self, job_id: str, attempt_token: str) -> RemoteAttempt:
        if self.transport_unknown:
            return RemoteAttempt(AttemptState.UNKNOWN, detail='simulated transport ambiguity')
        return self.attempts.get((job_id, attempt_token), RemoteAttempt(AttemptState.MISSING))

    def stage(self, local_path: Path, remote_path: str) -> None:
        dst = self.root / remote_path.lstrip('/')
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local_path, dst)

    def launch(self, job_id: str, attempt_token: str, command: Sequence[str]) -> RemoteAttempt:
        key = (job_id, attempt_token)
        existing = self.attempts.get(key)
        if existing is not None:
            return existing
        self.launch_count += 1
        state = RemoteAttempt(AttemptState.RUNNING)
        self.attempts[key] = state
        return state

    def finish(self, job_id: str, attempt_token: str, *, success: bool = True, output_path: str = '') -> None:
        state = AttemptState.SUCCEEDED if success else AttemptState.FAILED
        self.attempts[(job_id, attempt_token)] = RemoteAttempt(state, 0 if success else 1, output_path)

    def collect(self, remote_path: str, local_path: Path) -> None:
        src = self.root / remote_path.lstrip('/')
        local_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, local_path)

    def stop_compute(self) -> None:
        self.stop_count += 1
        self.worker_state = WorkerState.STOPPED
