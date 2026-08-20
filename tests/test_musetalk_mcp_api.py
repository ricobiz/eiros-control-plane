from pathlib import Path

import runtime.musetalk_job_mcp_server as server


def test_binary_create_status_and_result(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(server, 'STATE_ROOT', tmp_path/'state')
    server._reset_for_tests()
    created=server.musetalk_job_create('face.mp4', b'video', 'voice.wav', b'audio')
    assert created['job_id']
    assert server.musetalk_job_status(created['job_id'])['state']=='queued'

    svc=server._service()
    job_id=created['job_id']
    from runtime.musetalk_jobs.models import JobState
    for state in [JobState.PROVISIONING, JobState.STAGING, JobState.RUNNING, JobState.COLLECTING]:
        svc.store.transition(job_id,state,expected=svc.store.get_job(job_id).state)
    out=svc.artifacts.output_path(job_id); out.write_bytes(b'mp4bytes')
    svc.store.transition(job_id,JobState.DONE,expected=JobState.COLLECTING,output_path=str(out))
    assert server.musetalk_job_download(job_id)==b'mp4bytes'


def test_upload_filename_is_used_only_for_safe_suffix(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(server, 'STATE_ROOT', tmp_path/'state')
    server._reset_for_tests()
    created=server.musetalk_job_create('../../evil.mp4', b'video', '$(id).wav', b'audio')
    svc=server._service()
    job_dir=svc.artifacts.output_path(created['job_id']).parent
    names={p.name for p in job_dir.iterdir()}
    assert 'input.mp4' in names and 'input.wav' in names
    assert not any('evil' in n or '$(' in n for n in names)
