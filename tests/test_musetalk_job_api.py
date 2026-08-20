from pathlib import Path
import pytest

from runtime.musetalk_jobs.api import MuseTalkJobAPI, ResultUnavailable
from runtime.musetalk_jobs.artifacts import ArtifactStore
from runtime.musetalk_jobs.models import JobState
from runtime.musetalk_jobs.store import JobStore


def make(tmp_path: Path):
    store=JobStore(tmp_path/'jobs.sqlite3')
    artifacts=ArtifactStore(tmp_path/'artifacts')
    return store, artifacts, MuseTalkJobAPI(store, artifacts)


def media(tmp_path: Path):
    v=tmp_path/'v.mp4'; a=tmp_path/'a.wav'; v.write_bytes(b'video'); a.write_bytes(b'audio'); return v,a


def test_create_returns_job_id_and_status(tmp_path: Path):
    store, artifacts, api=make(tmp_path); v,a=media(tmp_path)
    created=api.create(v,a)
    assert created['job_id']
    assert created['state']=='queued'
    assert api.status(created['job_id'])['state']=='queued'


def test_result_unavailable_until_done_and_available_after(tmp_path: Path):
    store, artifacts, api=make(tmp_path); v,a=media(tmp_path)
    job_id=api.create(v,a)['job_id']
    with pytest.raises(ResultUnavailable): api.result(job_id)
    for state in [JobState.PROVISIONING, JobState.STAGING, JobState.RUNNING, JobState.COLLECTING]:
        store.transition(job_id,state,expected=store.get_job(job_id).state)
    out=artifacts.output_path(job_id); out.write_bytes(b'mp4')
    store.transition(job_id,JobState.DONE,expected=JobState.COLLECTING,output_path=str(out))
    assert api.result(job_id)==out


def test_cancel_is_idempotent(tmp_path: Path):
    store, artifacts, api=make(tmp_path); v,a=media(tmp_path)
    job_id=api.create(v,a)['job_id']
    assert api.cancel(job_id)['state']=='cancelled'
    assert api.cancel(job_id)['state']=='cancelled'


def test_bad_input_fails_create_without_queued_active_job(tmp_path: Path):
    store, artifacts, api=make(tmp_path)
    bad=tmp_path/'x.txt'; bad.write_bytes(b'x'); a=tmp_path/'a.wav'; a.write_bytes(b'a')
    with pytest.raises(Exception): api.create(bad,a)
    assert store.list_active()==[]
