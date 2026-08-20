# EIROS MuseTalk Job Service

Durable MuseTalk V1.5 rendering controlled by the EIROS VPS. The VPS owns job state and artifacts; RunPod is an ephemeral GPU worker.

## Runtime

- Job reconciler: `eiros-musetalk-jobs.service`
- Private MCP API: `eiros-musetalk-mcp.service`
- MCP bind: `127.0.0.1:8795/mcp`
- State root: `/var/lib/eiros/musetalk-jobs`
- RunPod target cache: `/var/lib/eiros/musetalk/runpod-target.json`
- Root-only environment: `/etc/eiros/musetalk-jobs.env`
- SSH key: `/root/.ssh/eiros_runpod`

The lifecycle provider auto-discovers the single reusable non-terminated Pod when `RUNPOD_POD_ID` is empty, starts it through the RunPod REST API, refreshes the current public SSH endpoint, and stops compute after the idle grace period. Automatic delete/terminate is not implemented.

## Recovery rules

A transport failure is treated as unknown until remote attempt evidence is inspected. Every render uses an immutable `job_id` and attempt token; existing `pid`, `exit_code`, and result evidence prevents blind duplicate launches. Inputs and outputs remain durable on the VPS.

The worker repairs the RunPod `PUBLIC_KEY` environment before lifecycle start so resumed/reset Pods regain the EIROS SSH key. Since RunPod container-disk packages are ephemeral, each render verifies `ffmpeg` and installs it only when absent. Torch model cache is redirected to persistent `/workspace/.cache/torch`.

## Live acceptance evidence — 2026-08-20

Live job `95da9c18-2fa3-4161-a06b-b588d7904762` completed `queued -> provisioning -> running -> collecting -> done` with zero render retries. The input was the upstream MuseTalk `yongen.mp4` + `yongen.wav` sample. The collected VPS artifact is:

`/var/lib/eiros/musetalk-jobs/artifacts/95da9c18-2fa3-4161-a06b-b588d7904762/result.mp4`

`ffprobe` verified H.264 video at 704x1216, AAC audio, 8.0 seconds duration, and 871598 bytes. After the queue became empty and the idle grace expired, the previous RunPod SSH endpoint stopped accepting connections while both EIROS services remained active.

## Verification

Run MuseTalk-specific tests from the feature checkout with the project interpreter:

`PYTHONPATH=$PWD /opt/eiros-control-plane/venv/bin/pytest -q tests/test_musetalk_*`

Run the full project suite:

`PYTHONPATH=$PWD /opt/eiros-control-plane/venv/bin/pytest -q`
