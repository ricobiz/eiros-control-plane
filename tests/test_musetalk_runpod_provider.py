from pathlib import Path

from runtime.musetalk_jobs.fakes import FakeRunPodProvider
from runtime.musetalk_jobs.runpod import AttemptState, WorkerState


def test_fake_provider_launch_is_idempotent(tmp_path: Path):
    p = FakeRunPodProvider(tmp_path)
    assert p.ensure_running().state is WorkerState.RUNNING
    p.launch('job1', 'attempt1', ['python', '-m', 'scripts.inference'])
    p.launch('job1', 'attempt1', ['python', '-m', 'scripts.inference'])
    assert p.launch_count == 1
    assert p.inspect_attempt('job1', 'attempt1').state is AttemptState.RUNNING


def test_fake_provider_models_unknown_transport_without_duplicate(tmp_path: Path):
    p = FakeRunPodProvider(tmp_path)
    p.launch('job1', 'attempt1', ['x'])
    p.transport_unknown = True
    status = p.inspect_attempt('job1', 'attempt1')
    assert status.state is AttemptState.UNKNOWN
    p.transport_unknown = False
    assert p.inspect_attempt('job1', 'attempt1').state is AttemptState.RUNNING
    assert p.launch_count == 1


def test_stop_compute_is_non_destructive(tmp_path: Path):
    p = FakeRunPodProvider(tmp_path)
    p.stop_compute()
    assert p.stop_count == 1
    assert p.worker_state is WorkerState.STOPPED
    assert not hasattr(p, 'delete_pod')
