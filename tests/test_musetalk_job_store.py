from pathlib import Path
import pytest

from runtime.musetalk_jobs.models import JobState
from runtime.musetalk_jobs.store import JobStore, InvalidTransition


def test_create_reload_and_attempt_stability(tmp_path: Path):
    db = tmp_path / 'jobs.sqlite3'
    s1 = JobStore(db)
    job = s1.create_job()
    assert job.state is JobState.QUEUED
    assert job.job_id
    assert job.attempt_token
    s2 = JobStore(db)
    loaded = s2.get_job(job.job_id)
    assert loaded.job_id == job.job_id
    assert loaded.attempt_token == job.attempt_token


def test_legal_and_illegal_transitions(tmp_path: Path):
    store = JobStore(tmp_path / 'jobs.sqlite3')
    job = store.create_job()
    job = store.transition(job.job_id, JobState.PROVISIONING, expected=JobState.QUEUED)
    assert job.state is JobState.PROVISIONING
    with pytest.raises(InvalidTransition):
        store.transition(job.job_id, JobState.DONE, expected=JobState.PROVISIONING)


def test_list_active_excludes_terminal(tmp_path: Path):
    store = JobStore(tmp_path / 'jobs.sqlite3')
    a = store.create_job()
    b = store.create_job()
    store.transition(a.job_id, JobState.CANCELLED, expected=JobState.QUEUED)
    active = store.list_active()
    assert [j.job_id for j in active] == [b.job_id]
