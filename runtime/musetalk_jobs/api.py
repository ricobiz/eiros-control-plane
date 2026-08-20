from __future__ import annotations

from pathlib import Path

from .artifacts import ArtifactStore
from .models import JobState, TERMINAL_STATES
from .store import JobStore


class ResultUnavailable(RuntimeError):
    pass


class MuseTalkJobAPI:
    def __init__(self, store: JobStore, artifacts: ArtifactStore):
        self.store = store
        self.artifacts = artifacts

    @staticmethod
    def _payload(job) -> dict:
        return {
            'job_id': job.job_id,
            'state': job.state.value,
            'created_at': job.created_at,
            'updated_at': job.updated_at,
            'retries': job.retries,
            'error': job.error,
            'output_path': job.output_path,
        }

    def create(self, video_path: str | Path, audio_path: str | Path) -> dict:
        job = self.store.create_job()
        try:
            self.artifacts.stage_inputs(job.job_id, video_path, audio_path)
        except Exception as exc:
            self.store.transition(job.job_id, JobState.FAILED, expected=JobState.QUEUED, error=str(exc)[-2000:])
            raise
        return self._payload(self.store.get_job(job.job_id))

    def status(self, job_id: str) -> dict:
        return self._payload(self.store.get_job(job_id))

    def result(self, job_id: str) -> Path:
        job = self.store.get_job(job_id)
        if job.state is not JobState.DONE:
            raise ResultUnavailable(f'job {job_id} is {job.state.value}')
        path = Path(job.output_path)
        if not path.is_file() or path.stat().st_size <= 0:
            raise ResultUnavailable('result artifact is missing')
        return path

    def cancel(self, job_id: str) -> dict:
        job = self.store.get_job(job_id)
        if job.state in TERMINAL_STATES:
            return self._payload(job)
        job = self.store.transition(job.job_id, JobState.CANCELLED, expected=job.state)
        return self._payload(job)
