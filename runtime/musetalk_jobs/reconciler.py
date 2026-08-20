from __future__ import annotations

from .models import JobState, RenderJob
from .runpod import AttemptState, RunPodProvider, WorkerState
from .runner import MuseTalkRunner
from .store import JobStore


class Reconciler:
    def __init__(self, store: JobStore, runner: MuseTalkRunner, provider: RunPodProvider, *, max_infra_retries: int = 2):
        self.store = store
        self.runner = runner
        self.provider = provider
        self.max_infra_retries = max(0, int(max_infra_retries))

    def _retry_or_fail(self, job: RenderJob, fallback: JobState, exc: Exception) -> RenderJob:
        message = str(exc)[-2000:]
        if job.retries < self.max_infra_retries:
            return self.store.transition(
                job.job_id,
                fallback,
                expected=job.state,
                error=message,
                increment_retries=True,
            )
        return self.store.transition(job.job_id, JobState.FAILED, expected=job.state, error=message)

    def tick(self, job_id: str) -> RenderJob:
        job = self.store.get_job(job_id)
        if job.state in {JobState.DONE, JobState.FAILED, JobState.CANCELLED}:
            return job

        if job.state is JobState.QUEUED:
            return self.store.transition(job.job_id, JobState.PROVISIONING, expected=JobState.QUEUED)

        if job.state is JobState.PROVISIONING:
            try:
                worker = self.provider.ensure_running()
                if worker.state is not WorkerState.RUNNING:
                    raise RuntimeError(f'worker is {worker.state.value}')
                return self.store.transition(job.job_id, JobState.STAGING, expected=JobState.PROVISIONING, error='')
            except Exception as exc:
                return self._retry_or_fail(job, JobState.QUEUED, exc)

        if job.state is JobState.STAGING:
            try:
                remote = self.runner.inspect_or_start(job)
            except Exception as exc:
                return self._retry_or_fail(job, JobState.QUEUED, exc)
            if remote.state in {AttemptState.RUNNING, AttemptState.UNKNOWN}:
                return self.store.transition(job.job_id, JobState.RUNNING, expected=JobState.STAGING, error='')
            if remote.state is AttemptState.SUCCEEDED:
                return self.store.transition(job.job_id, JobState.COLLECTING, expected=JobState.STAGING, error='')
            if remote.state is AttemptState.FAILED:
                return self.store.transition(
                    job.job_id, JobState.FAILED, expected=JobState.STAGING,
                    error=f'remote inference failed with exit code {remote.exit_code}',
                )
            return job

        if job.state is JobState.RUNNING:
            try:
                remote = self.provider.inspect_attempt(job.job_id, job.attempt_token)
            except Exception:
                return job
            if remote.state in {AttemptState.RUNNING, AttemptState.UNKNOWN}:
                return job
            if remote.state is AttemptState.SUCCEEDED:
                return self.store.transition(job.job_id, JobState.COLLECTING, expected=JobState.RUNNING, error='')
            if remote.state is AttemptState.FAILED:
                return self.store.transition(
                    job.job_id, JobState.FAILED, expected=JobState.RUNNING,
                    error=f'remote inference failed with exit code {remote.exit_code}',
                )
            # Missing is ambiguous after transport/process restart; never blind-relaunch a running attempt.
            return job

        if job.state is JobState.COLLECTING:
            try:
                final = self.runner.collect(job)
            except Exception as exc:
                if job.retries < self.max_infra_retries:
                    return self.store.transition(
                        job.job_id, JobState.RUNNING, expected=JobState.COLLECTING,
                        error=str(exc)[-2000:], increment_retries=True,
                    )
                return self.store.transition(
                    job.job_id, JobState.FAILED, expected=JobState.COLLECTING,
                    error=str(exc)[-2000:],
                )
            return self.store.transition(
                job.job_id, JobState.DONE, expected=JobState.COLLECTING,
                error='', output_path=str(final),
            )

        return job
