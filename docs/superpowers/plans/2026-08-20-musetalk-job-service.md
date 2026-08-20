# MuseTalk Job Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a durable VPS-controlled MuseTalk V1.5 render service with idempotent jobs, recovery, artifact collection, and automatic RunPod compute shutdown.

**Architecture:** EIROS VPS owns durable SQLite job state and artifacts; RunPod is an ephemeral single-GPU worker behind a provider interface. A reconciler advances persisted states and verifies remote evidence before repeating side effects.

**Tech Stack:** Python 3.12, stdlib sqlite3/dataclasses/pathlib/subprocess, existing EIROS MCP/HTTP runtime patterns, pytest, MuseTalk V1.5 on RunPod.

**Spec:** `docs/superpowers/specs/2026-08-20-musetalk-job-service-design.md`

## Global Constraints
- VPS is the source of truth; RunPod is never the durable job store.
- Never automatically delete/terminate the RunPod pod or volume; only stop compute after idle grace.
- Every side effect is keyed by immutable job_id + attempt token.
- A transport timeout is UNKNOWN until remote/local evidence is reconciled.
- No raw uploaded filename may become a shell argument or filesystem path.
- Completion requires a collected, non-empty MP4 artifact on the VPS.

---

### Task 1: Durable job model and transition store

**Files:**
- Create: `runtime/musetalk_jobs/__init__.py`
- Create: `runtime/musetalk_jobs/models.py`
- Create: `runtime/musetalk_jobs/store.py`
- Test: `tests/test_musetalk_job_store.py`

**Interfaces:**
- Produces: `JobState`, `RenderJob`, `JobStore.create_job()`, `get_job()`, `transition()`, `list_active()`.

- [ ] Write failing tests proving UUID creation, persisted reload, legal transitions, illegal-transition rejection, and attempt-token stability.
- [ ] Run `pytest -q tests/test_musetalk_job_store.py` and verify failure because modules do not exist.
- [ ] Implement enums/dataclass and SQLite schema with WAL, timestamps, error fields, attempt token, and transactional compare-and-set transitions.
- [ ] Run the test file and verify all tests pass.
- [ ] Commit only Task 1 files with `feat: add durable MuseTalk job store`.

### Task 2: Artifact validation and atomic storage

**Files:**
- Create: `runtime/musetalk_jobs/artifacts.py`
- Test: `tests/test_musetalk_artifacts.py`

**Interfaces:**
- Consumes: job UUID from Task 1.
- Produces: `ArtifactStore.stage_inputs(job_id, video, audio)`, `output_path(job_id)`, `commit_output(job_id, temp_path)`.

- [ ] Write failing tests for UUID-only directories, fixed internal filenames, extension/size rejection, path traversal resistance, and atomic output commit.
- [ ] Run tests and verify expected failures.
- [ ] Implement artifact store using `pathlib`, configured byte limits, temporary files, fsync/rename semantics, and non-empty MP4 validation.
- [ ] Run tests and verify pass.
- [ ] Commit with `feat: add MuseTalk artifact store`.

### Task 3: RunPod provider boundary and fake provider

**Files:**
- Create: `runtime/musetalk_jobs/runpod.py`
- Create: `runtime/musetalk_jobs/fakes.py`
- Test: `tests/test_musetalk_runpod_provider.py`

**Interfaces:**
- Produces: `WorkerStatus`, `RemoteAttempt`, `RunPodProvider.ensure_running()`, `inspect_attempt()`, `stage()`, `launch()`, `collect()`, `stop_compute()` and `FakeRunPodProvider`.

- [ ] Write contract tests proving launch idempotency, endpoint refresh, UNKNOWN transport result handling, and that `stop_compute()` has no delete/terminate operation.
- [ ] Run tests and verify failure.
- [ ] Implement protocol/types plus fake provider; implement real provider as an adapter around the existing audited RunPod/VPS execution path, with endpoint resolution separated from job state.
- [ ] Run contract tests and verify pass.
- [ ] Commit with `feat: add RunPod worker provider`.

### Task 4: MuseTalk per-job runner

**Files:**
- Create: `runtime/musetalk_jobs/runner.py`
- Test: `tests/test_musetalk_runner.py`

**Interfaces:**
- Consumes: `ArtifactStore`, `RunPodProvider`, `RenderJob`.
- Produces: deterministic remote directory/config/command derived from job_id + attempt token and `Runner.inspect_or_start(job)` / `collect(job)`.

- [ ] Write failing tests proving generated config targets MuseTalk V1.5, raw filenames never enter commands, the same attempt never launches twice, and collection requires a valid MP4.
- [ ] Run tests and verify failure.
- [ ] Implement fixed remote naming, YAML/JSON config generation without user-controlled shell fragments, remote attempt marker, launch, inspect, and atomic collection.
- [ ] Run tests and verify pass.
- [ ] Commit with `feat: add idempotent MuseTalk runner`.

### Task 5: Reconciler and restart recovery

**Files:**
- Create: `runtime/musetalk_jobs/reconciler.py`
- Test: `tests/test_musetalk_reconciler.py`

**Interfaces:**
- Consumes: `JobStore`, `Runner`, `RunPodProvider`.
- Produces: `Reconciler.tick(now)` and deterministic recovery/state advancement.

- [ ] Write failing table-driven tests for queued success, provisioning failure/retry, SSH timeout with remote process still running, process finished with output, process missing without output, collection retry, and daemon restart with persisted running job.
- [ ] Run tests and verify failure.
- [ ] Implement one-state-at-a-time reconciliation with bounded infrastructure retries and no blind relaunch of running/unknown attempts.
- [ ] Run tests and verify pass.
- [ ] Commit with `feat: add MuseTalk job reconciler`.

### Task 6: Idle GPU shutdown policy

**Files:**
- Modify: `runtime/musetalk_jobs/reconciler.py`
- Test: `tests/test_musetalk_idle_shutdown.py`

**Interfaces:**
- Produces: idle timestamp tracking and `maybe_stop_idle_worker(now)`.

- [ ] Write failing tests proving GPU stays on with active/queued work, starts grace only after queue empties, resets grace when work arrives, calls stop exactly once after grace, and never calls any destructive provider action.
- [ ] Run tests and verify failure.
- [ ] Implement configurable idle grace (default 120 seconds) and stop-compute gating.
- [ ] Run tests and verify pass.
- [ ] Commit with `feat: stop idle MuseTalk GPU safely`.

### Task 7: Private job API

**Files:**
- Create: `runtime/musetalk_jobs/api.py`
- Create: `runtime/musetalk_jobs/service.py`
- Test: `tests/test_musetalk_job_api.py`

**Interfaces:**
- Produces: create/status/result/cancel service methods and connector-facing tool handlers returning structured JSON.

- [ ] Write failing API tests for create returning job_id, status transitions, result unavailable before done, result path after done, idempotent cancel, and malformed input rejection.
- [ ] Run tests and verify failure.
- [ ] Implement service layer and private connector handlers following existing EIROS runtime conventions; do not expose an unauthenticated public route.
- [ ] Run tests and verify pass.
- [ ] Commit with `feat: expose private MuseTalk job API`.

### Task 8: Service lifecycle and crash recovery integration

**Files:**
- Create: `deploy/eiros-musetalk-jobs.service`
- Modify: `deploy/manifest.json`
- Test: `tests/test_musetalk_service_lifecycle.py`

**Interfaces:**
- Consumes: `runtime.musetalk_jobs.service`.
- Produces: managed daemon that restarts safely and resumes persisted non-terminal jobs.

- [ ] Write failing lifecycle tests for service command/config and restart recovery using a temporary SQLite DB + fake provider.
- [ ] Run tests and verify failure.
- [ ] Add systemd unit/manifest integration with bounded restart policy and persistent VPS state paths.
- [ ] Run lifecycle tests and full `pytest -q tests/test_musetalk_*`.
- [ ] Commit with `feat: manage MuseTalk job service`.

### Task 9: End-to-end fake-provider acceptance test

**Files:**
- Create: `tests/test_musetalk_e2e.py`

**Interfaces:**
- Exercises all public service interfaces from Tasks 1-8.

- [ ] Write an acceptance test that stages fake media, creates a job, advances ticks through provisioning/staging/running/collecting/done, verifies one launch only, validates returned MP4, then advances time and verifies one compute stop.
- [ ] Run the test and fix only integration defects revealed by it.
- [ ] Run `pytest -q tests/test_musetalk_*` twice to prove repeatability.
- [ ] Commit with `test: cover MuseTalk job service end to end`.

### Task 10: Live RunPod smoke test and operational handoff

**Files:**
- Create: `docs/MUSETALK_JOB_SERVICE.md`
- Modify: `docs/EIROS_CURRENT_HANDOFF.json`

**Interfaces:**
- Validates the real provider against the already-proven MuseTalk V1.5 worker.

- [ ] Start compute only for this test and resolve the current endpoint through the provider.
- [ ] Submit a short real video/audio pair through the new service API; do not edit MuseTalk YAML manually.
- [ ] Verify durable state reaches done, output MP4 exists on VPS and is non-empty/playable, and exactly one remote attempt was launched.
- [ ] Verify the worker stops after idle grace while the RunPod volume remains intact.
- [ ] Run the complete MuseTalk test suite once more and record exact operational commands/state paths in `docs/MUSETALK_JOB_SERVICE.md`.
- [ ] Update handoff state and commit with `docs: hand off MuseTalk job service`.
