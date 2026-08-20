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



def runtime_config_from_env() -> dict[str, object]:
    def first(*names: str, default: str = '') -> str:
        for name in names:
            value = os.environ.get(name)
            if value not in (None, ''):
                return value
        return default
    return {
        'state_root': first('EIROS_MUSETALK_STATE_ROOT', 'MUSETALK_STATE_DIR', default='/var/lib/eiros/musetalk-jobs'),
        'target_file': first('EIROS_RUNPOD_TARGET_FILE', 'MUSETALK_RUNPOD_TARGET', default='/opt/eiros-control-plane/runtime/runpod_target.json'),
        'key_file': first('EIROS_RUNPOD_KEY_FILE', 'MUSETALK_RUNPOD_KEY', default='/root/.ssh/eiros_runpod'),
        'idle_grace': int(first('EIROS_MUSETALK_IDLE_GRACE_SECONDS', 'MUSETALK_IDLE_GRACE_SECONDS', default='120')),
        'tick_seconds': max(0.5, float(first('EIROS_MUSETALK_TICK_SECONDS', default='2'))),
        'api_key': first('EIROS_RUNPOD_API_KEY', 'RUNPOD_API_KEY'),
        'pod_id': first('EIROS_RUNPOD_POD_ID', 'RUNPOD_POD_ID'),
        'start_cmd': shlex.split(first('EIROS_RUNPOD_START_CMD')),
        'stop_cmd': shlex.split(first('EIROS_RUNPOD_STOP_CMD')),
    }

def main() -> int:
    from .runpod import SshRunPodProvider
    from .runpod_api import RunPodRestLifecycle

    cfg = runtime_config_from_env()
    lifecycle = RunPodRestLifecycle(str(cfg['api_key']), str(cfg['pod_id'])) if cfg['api_key'] else None
    provider = SshRunPodProvider(
        str(cfg['target_file']), str(cfg['key_file']),
        start_command=cfg['start_cmd'], stop_command=cfg['stop_cmd'], lifecycle=lifecycle,
    )
    service = MuseTalkJobService.build(str(cfg['state_root']), provider, idle_grace_seconds=int(cfg['idle_grace']))
    while True:
        service.tick_once()
        time.sleep(float(cfg['tick_seconds']))


if __name__ == '__main__':
    raise SystemExit(main())
