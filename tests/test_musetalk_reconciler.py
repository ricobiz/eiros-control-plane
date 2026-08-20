from pathlib import Path

from runtime.musetalk_jobs.artifacts import ArtifactStore
from runtime.musetalk_jobs.fakes import FakeRunPodProvider
from runtime.musetalk_jobs.models import JobState
from runtime.musetalk_jobs.reconciler import Reconciler
from runtime.musetalk_jobs.runner import MuseTalkRunner
from runtime.musetalk_jobs.runpod import AttemptState, RemoteAttempt, WorkerState, WorkerStatus
from runtime.musetalk_jobs.store import JobStore


def setup_job(tmp_path: Path):
    store = JobStore(tmp_path/'jobs.sqlite3')
    artifacts = ArtifactStore(tmp_path/'artifacts')
    job = store.create_job()
    v=tmp_path/'v.mp4'; a=tmp_path/'a.wav'; v.write_bytes(b'video'); a.write_bytes(b'audio')
    artifacts.stage_inputs(job.job_id, v, a)
    provider = FakeRunPodProvider(tmp_path/'remote')
    runner = MuseTalkRunner(artifacts, provider)
    return store, artifacts, job, provider, runner


def test_success_flow_is_persisted_one_state_at_a_time(tmp_path: Path):
    store, artifacts, job, p, runner = setup_job(tmp_path)
    r = Reconciler(store, runner, p)
    assert r.tick(job.job_id).state is JobState.PROVISIONING
    assert r.tick(job.job_id).state is JobState.STAGING
    assert r.tick(job.job_id).state is JobState.RUNNING
    assert p.launch_count == 1
    remote = runner.remote_output(store.get_job(job.job_id))
    out = tmp_path/'remote'/remote.lstrip('/'); out.parent.mkdir(parents=True, exist_ok=True); out.write_bytes(b'mp4')
    p.finish(job.job_id, job.attempt_token, output_path=remote)
    assert r.tick(job.job_id).state is JobState.COLLECTING
    done = r.tick(job.job_id)
    assert done.state is JobState.DONE
    assert Path(done.output_path).is_file()
    assert p.launch_count == 1


def test_unknown_transport_does_not_relaunch_running_job(tmp_path: Path):
    store, artifacts, job, p, runner = setup_job(tmp_path)
    r = Reconciler(store, runner, p)
    for _ in range(3): r.tick(job.job_id)
    assert store.get_job(job.job_id).state is JobState.RUNNING
    p.transport_unknown = True
    same = r.tick(job.job_id)
    assert same.state is JobState.RUNNING
    assert p.launch_count == 1


def test_remote_failure_becomes_failed(tmp_path: Path):
    store, artifacts, job, p, runner = setup_job(tmp_path)
    r = Reconciler(store, runner, p)
    for _ in range(3): r.tick(job.job_id)
    p.finish(job.job_id, job.attempt_token, success=False)
    failed = r.tick(job.job_id)
    assert failed.state is JobState.FAILED
    assert 'exit code 1' in failed.error


def test_restart_recovery_inspects_existing_attempt_without_duplicate(tmp_path: Path):
    store, artifacts, job, p, runner = setup_job(tmp_path)
    r1 = Reconciler(store, runner, p)
    for _ in range(3): r1.tick(job.job_id)
    assert p.launch_count == 1
    r2 = Reconciler(JobStore(store.path), MuseTalkRunner(artifacts, p), p)
    recovered = r2.tick(job.job_id)
    assert recovered.state is JobState.RUNNING
    assert p.launch_count == 1
