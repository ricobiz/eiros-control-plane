from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from .api import MuseTalkJobAPI
from .artifacts import ArtifactStore
from .reconciler import Reconciler
from .runpod import RunPodProvider
from .runner import MuseTalkRunner
from .store import JobStore


@dataclass
class MuseTalkJobService:
    store: JobStore
    artifacts: ArtifactStore
    provider: RunPodProvider
    runner: MuseTalkRunner
    reconciler: Reconciler
    api: MuseTalkJobAPI

    @classmethod
    def build(
        cls,
        state_root: str | Path,
        provider: RunPodProvider,
        *,
        idle_grace_seconds: int = 120,
    ) -> 'MuseTalkJobService':
        root = Path(state_root)
        root.mkdir(parents=True, exist_ok=True)
        store = JobStore(root / 'jobs.sqlite3')
        artifacts = ArtifactStore(root / 'artifacts')
        runner = MuseTalkRunner(artifacts, provider)
        reconciler = Reconciler(store, runner, provider, idle_grace_seconds=idle_grace_seconds)
        api = MuseTalkJobAPI(store, artifacts)
        return cls(store, artifacts, provider, runner, reconciler, api)

    def tick_once(self, now: float | None = None) -> None:
        for job in list(self.store.list_active()):
            self.reconciler.tick(job.job_id)
        self.reconciler.maybe_stop_idle_worker(time.time() if now is None else now)
