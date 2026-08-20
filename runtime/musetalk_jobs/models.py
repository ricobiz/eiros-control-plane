from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class JobState(StrEnum):
    QUEUED = "queued"
    PROVISIONING = "provisioning"
    STAGING = "staging"
    RUNNING = "running"
    COLLECTING = "collecting"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATES = {JobState.DONE, JobState.FAILED, JobState.CANCELLED}


@dataclass(frozen=True)
class RenderJob:
    job_id: str
    attempt_token: str
    state: JobState
    created_at: float
    updated_at: float
    retries: int = 0
    error: str = ""
    output_path: str = ""
