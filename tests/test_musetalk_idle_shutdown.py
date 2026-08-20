from pathlib import Path

from runtime.musetalk_jobs.artifacts import ArtifactStore
from runtime.musetalk_jobs.fakes import FakeRunPodProvider
from runtime.musetalk_jobs.reconciler import Reconciler
from runtime.musetalk_jobs.runner import MuseTalkRunner
from runtime.musetalk_jobs.store import JobStore


def make(tmp_path: Path, grace=120):
    store = JobStore(tmp_path/'jobs.sqlite3')
    artifacts = ArtifactStore(tmp_path/'artifacts')
    provider = FakeRunPodProvider(tmp_path/'remote')
    runner = MuseTalkRunner(artifacts, provider)
    return store, provider, Reconciler(store, runner, provider, idle_grace_seconds=grace)


def test_gpu_stays_on_with_active_work(tmp_path: Path):
    store, p, r = make(tmp_path)
    store.create_job()
    assert r.maybe_stop_idle_worker(100) is False
    assert p.stop_count == 0


def test_grace_starts_when_queue_empty_and_stops_once(tmp_path: Path):
    store, p, r = make(tmp_path, grace=10)
    assert r.maybe_stop_idle_worker(100) is False
    assert r.maybe_stop_idle_worker(109) is False
    assert r.maybe_stop_idle_worker(110) is True
    assert p.stop_count == 1
    assert r.maybe_stop_idle_worker(120) is False
    assert p.stop_count == 1


def test_new_work_resets_idle_grace(tmp_path: Path):
    store, p, r = make(tmp_path, grace=10)
    r.maybe_stop_idle_worker(100)
    job = store.create_job()
    r.maybe_stop_idle_worker(105)
    store.transition(job.job_id, __import__('runtime.musetalk_jobs.models', fromlist=['JobState']).JobState.CANCELLED, expected=__import__('runtime.musetalk_jobs.models', fromlist=['JobState']).JobState.QUEUED)
    assert r.maybe_stop_idle_worker(106) is False
    assert r.maybe_stop_idle_worker(115) is False
    assert r.maybe_stop_idle_worker(116) is True
