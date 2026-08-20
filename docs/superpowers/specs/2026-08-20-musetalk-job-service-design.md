# MuseTalk Job Service Design

## Goal
Turn the proven MuseTalk V1.5 RunPod installation into a durable EIROS service where a client submits video + audio and receives a rendered MP4 without manually editing YAML, opening a terminal, or managing the GPU lifecycle.

## Definition of Done
A caller uploads one video and one audio file, receives a stable job ID, and can observe the job move through queued -> provisioning -> running -> collecting -> done/failed. A successful job returns a playable MP4. Repeating the same start/collect operation after a timeout or transport failure must not create a duplicate inference. RunPod/SSH interruption must leave enough durable state on the VPS to resume or fail deterministically. GPU compute is stopped after the queue is empty and an idle grace period expires. The service must never delete the RunPod volume as part of automatic shutdown.

## Architecture
The EIROS VPS is the control plane and source of truth. RunPod is an ephemeral GPU worker only. Job metadata, state transitions, input artifacts, output artifacts, attempt identifiers, timestamps, and failure details live on the VPS. RunPod receives staged inputs, runs MuseTalk V1.5, and exposes the generated artifact for collection.

The first implementation uses a persistent SQLite job store and filesystem artifact store on the VPS, plus a single-worker reconciler. SQLite is deliberately chosen over Redis/Postgres for the first version because the workload is serialized by one expensive GPU and durability matters more than distributed throughput. The state-machine boundary allows replacing storage or adding multiple workers later without changing the public API.

## Job State Machine
States: queued, provisioning, staging, running, collecting, done, failed, cancelled.

Every transition is persisted before the next side effect. A job owns an immutable UUID and a render attempt token. Side-effecting operations are idempotent against that token. On process restart the reconciler reloads non-terminal jobs and inspects remote/local evidence before deciding whether to resume, collect, retry, or fail.

## Components
`runtime/musetalk_jobs/models.py` defines job/state records. `store.py` owns SQLite transactions and legal state transitions. `artifacts.py` owns validated input/output paths and atomic moves. `runpod.py` is the only module allowed to provision/stop or execute on RunPod. `runner.py` stages files, creates per-job MuseTalk config, starts inference, and collects output. `reconciler.py` advances durable jobs and handles recovery. `api.py` exposes create/status/result/cancel operations. A small service entrypoint runs the API and reconciler.

## Data Flow
Create validates extensions/size, stores inputs under a job-specific VPS directory, inserts queued state, and returns job_id. Reconciler ensures GPU availability, stages inputs into a job-specific RunPod directory, writes a generated inference config, and launches exactly one inference for the attempt token. Completion is detected from process exit plus an output-file sanity check, not log text alone. Output is copied atomically back to the VPS before state becomes done.

## RunPod Lifecycle
GPU start/stop is isolated behind a provider interface. Automatic shutdown happens only when no non-terminal jobs exist and the configured idle grace period has elapsed. Shutdown means stop compute only; automatic deletion/termination of the pod or volume is forbidden. Endpoint changes after migration/start are treated as normal and resolved by provider status rather than hard-coded into job records.

## Failure and Recovery
Transport timeout is UNKNOWN, not immediate failure: reconciler rechecks remote attempt marker/process/output. Failed inference records exit code and bounded stderr/log tail. Staging and collection use temporary names plus atomic rename. A stale running job is never blindly relaunched; remote attempt evidence is checked first. Jobs have bounded retries for infrastructure failures, while deterministic MuseTalk/input failures terminate as failed.

## Security and Limits
Uploaded filenames are never used as filesystem paths. Jobs use UUID directories and fixed internal names. Inputs are allowlisted by media type/extension and configured size limits. Shell arguments are not composed from raw user filenames. API access follows the existing private EIROS connector boundary; no public unauthenticated render endpoint is introduced.

## Testing
Unit tests cover legal transitions, idempotency, restart recovery decisions, artifact validation, idle shutdown gating, and command/config generation. Integration tests use a fake RunPod provider to exercise complete success/failure/recovery flows without GPU cost. One final live smoke test uses a short real video/audio pair on RunPod and verifies the returned MP4 before compute is stopped.
