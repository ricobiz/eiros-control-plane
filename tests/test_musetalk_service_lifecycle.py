from pathlib import Path

from runtime.musetalk_jobs.fakes import FakeRunPodProvider
from runtime.musetalk_jobs.models import JobState
from runtime.musetalk_jobs.service import MuseTalkJobService


def test_systemd_unit_uses_persistent_state_and_restart_policy():
    text=Path('deploy/eiros-musetalk-jobs.service').read_text()
    assert 'runtime.musetalk_jobs.service' in text
    assert 'Restart=on-failure' in text
    assert 'EIROS_MUSETALK_STATE_ROOT=/var/lib/eiros/musetalk-jobs' in text


def test_service_rebuild_recovers_persisted_running_job(tmp_path: Path):
    provider=FakeRunPodProvider(tmp_path/'remote')
    s1=MuseTalkJobService.build(tmp_path/'state', provider, idle_grace_seconds=1000)
    v=tmp_path/'v.mp4'; a=tmp_path/'a.wav'; v.write_bytes(b'video'); a.write_bytes(b'audio')
    job_id=s1.api.create(v,a)['job_id']
    for _ in range(3): s1.tick_once(1)
    assert s1.store.get_job(job_id).state is JobState.RUNNING
    launches=provider.launch_count
    s2=MuseTalkJobService.build(tmp_path/'state', provider, idle_grace_seconds=1000)
    s2.tick_once(2)
    assert s2.store.get_job(job_id).state is JobState.RUNNING
    assert provider.launch_count==launches


def test_units_load_root_only_runpod_environment_file():
    for path in ['deploy/eiros-musetalk-jobs.service','deploy/eiros-musetalk-mcp.service']:
        text=Path(path).read_text()
        assert 'EnvironmentFile=-/etc/eiros/musetalk-jobs.env' in text
    example=Path('deploy/musetalk-jobs.env.example').read_text()
    assert 'EIROS_RUNPOD_API_KEY=' in example
    assert 'EIROS_RUNPOD_POD_ID=' in example
