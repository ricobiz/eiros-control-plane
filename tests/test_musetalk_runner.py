from pathlib import Path

from runtime.musetalk_jobs.artifacts import ArtifactStore
from runtime.musetalk_jobs.fakes import FakeRunPodProvider
from runtime.musetalk_jobs.runner import MuseTalkRunner
from runtime.musetalk_jobs.store import JobStore
from runtime.musetalk_jobs.runpod import AttemptState


def _job(tmp_path: Path):
    store = JobStore(tmp_path / 'jobs.sqlite3')
    job = store.create_job()
    artifacts = ArtifactStore(tmp_path / 'artifacts')
    video = tmp_path / 'evil name;rm -rf.mp4'; video.write_bytes(b'video')
    audio = tmp_path / 'voice $(id).wav'; audio.write_bytes(b'audio')
    artifacts.stage_inputs(job.job_id, video, audio)
    return job, artifacts


def test_runner_generates_fixed_v15_paths_without_raw_names(tmp_path: Path):
    job, artifacts = _job(tmp_path)
    provider = FakeRunPodProvider(tmp_path / 'remote')
    runner = MuseTalkRunner(artifacts, provider)
    status = runner.inspect_or_start(job)
    assert status.state is AttemptState.RUNNING
    assert provider.launch_count == 1
    cmd = runner.command_for(job)
    joined = ' '.join(cmd)
    assert 'musetalkV15/unet.pth' in joined
    assert 'evil name' not in joined and '$(id)' not in joined
    cfg = (tmp_path / 'remote' / runner.remote_config(job).lstrip('/')).read_text()
    assert 'input.mp4' in cfg and 'input.wav' in cfg


def test_runner_same_attempt_does_not_launch_twice(tmp_path: Path):
    job, artifacts = _job(tmp_path)
    provider = FakeRunPodProvider(tmp_path / 'remote')
    runner = MuseTalkRunner(artifacts, provider)
    runner.inspect_or_start(job)
    runner.inspect_or_start(job)
    assert provider.launch_count == 1


def test_collect_requires_valid_mp4(tmp_path: Path):
    job, artifacts = _job(tmp_path)
    provider = FakeRunPodProvider(tmp_path / 'remote')
    runner = MuseTalkRunner(artifacts, provider)
    remote = runner.remote_output(job)
    src = tmp_path / 'remote' / remote.lstrip('/')
    src.parent.mkdir(parents=True, exist_ok=True); src.write_bytes(b'render')
    provider.finish(job.job_id, job.attempt_token, output_path=remote)
    final = runner.collect(job)
    assert final.read_bytes() == b'render'
