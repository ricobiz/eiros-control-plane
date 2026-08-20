from pathlib import Path

from runtime.musetalk_jobs.fakes import FakeRunPodProvider
from runtime.musetalk_jobs.models import JobState
from runtime.musetalk_jobs.service import MuseTalkJobService


def test_end_to_end_fake_provider_is_idempotent_and_stops_idle_gpu(tmp_path: Path):
    provider = FakeRunPodProvider(tmp_path/'remote')
    service = MuseTalkJobService.build(tmp_path/'state', provider, idle_grace_seconds=10)
    video=tmp_path/'clip.mp4'; audio=tmp_path/'voice.wav'
    video.write_bytes(b'video'); audio.write_bytes(b'audio')
    created=service.api.create(video,audio)
    job_id=created['job_id']

    service.tick_once(0)  # queued -> provisioning
    service.tick_once(1)  # provisioning -> staging
    service.tick_once(2)  # staging -> running + launch
    job=service.store.get_job(job_id)
    assert job.state is JobState.RUNNING
    assert provider.launch_count == 1

    # Repeated ticks while remote is still running do not launch again.
    service.tick_once(3); service.tick_once(4)
    assert provider.launch_count == 1

    remote=service.runner.remote_output(job)
    fake_out=tmp_path/'remote'/remote.lstrip('/')
    fake_out.parent.mkdir(parents=True, exist_ok=True)
    fake_out.write_bytes(b'playable-enough-test-mp4')
    provider.finish(job.job_id, job.attempt_token, output_path=remote)

    service.tick_once(5)  # running -> collecting
    service.tick_once(6)  # collecting -> done
    done=service.store.get_job(job_id)
    assert done.state is JobState.DONE
    result=service.api.result(job_id)
    assert result.read_bytes() == b'playable-enough-test-mp4'
    assert provider.launch_count == 1

    service.tick_once(7)   # idle timer was established when the job became done at t=6
    service.tick_once(15)  # nine idle seconds
    assert provider.stop_count == 0
    service.tick_once(16)  # ten idle seconds: grace expires
    assert provider.stop_count == 1
    service.tick_once(30)
    assert provider.stop_count == 1
