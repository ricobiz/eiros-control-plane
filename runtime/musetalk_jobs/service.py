from __future__ import annotations

import os
import shlex
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


def main() -> int:
    from .runpod import SshRunPodProvider
    from .runpod_api import RunPodRestLifecycle

    state_root = os.environ.get('EIROS_MUSETALK_STATE_ROOT', '/var/lib/eiros/musetalk-jobs')
    target_file = os.environ.get('EIROS_RUNPOD_TARGET_FILE', '/opt/eiros-control-plane/runtime/runpod_target.json')
    key_file = os.environ.get('EIROS_RUNPOD_KEY_FILE', '/root/.ssh/eiros_runpod')
    start_cmd = shlex.split(os.environ.get('EIROS_RUNPOD_START_CMD', ''))
    stop_cmd = shlex.split(os.environ.get('EIROS_RUNPOD_STOP_CMD', ''))
    idle_grace = int(os.environ.get('EIROS_MUSETALK_IDLE_GRACE_SECONDS', '120'))
    tick_seconds = max(0.5, float(os.environ.get('EIROS_MUSETALK_TICK_SECONDS', '2')))
    api_key = os.environ.get('EIROS_RUNPOD_API_KEY', '')
    pod_id = os.environ.get('EIROS_RUNPOD_POD_ID', '')
    lifecycle = RunPodRestLifecycle(api_key, pod_id) if api_key and pod_id else None
    provider = SshRunPodProvider(target_file, key_file, start_command=start_cmd, stop_command=stop_cmd, lifecycle=lifecycle)
    service = MuseTalkJobService.build(state_root, provider, idle_grace_seconds=idle_grace)
    while True:
        service.tick_once()
        time.sleep(tick_seconds)


if __name__ == '__main__':
    raise SystemExit(main())
