# LAM avatar pipeline — handoff 2026-09-04

Session paused for context limits, not for a technical blocker. Pod stopped
deliberately to stop burning RunPod balance while unattended.

## Pod

- Pod id `7r4emsgegttnxp`, name `eiros-lam-avatar-pass2`, RTX 4090, $0.74/hr.
- Resume with GraphQL `podResume(input:{podId:"7r4emsgegttnxp", gpuCount:1})`.
- API key lives in `/etc/eiros/musetalk-jobs.env` as `RUNPOD_API_KEY`.
- SSH key `/root/.ssh/eiros_runpod`. Port changes on every resume — re-read it
  from `pod.runtime.ports` (privatePort 22), do not reuse the old one.

## Why pass 1 (2026-08-28) produced only an mp4

Three independent causes, all now root-caused:

1. The browser renderer needs an OAC bundle (`skin.glb`, `animation.glb`,
   `offset.ply`, `vertex_order.json`). Only the `enable_oac_file` branch of
   `app_lam.py` emits it, and that branch needs Blender + FBX SDK. Neither was
   installed in pass 1.
2. The FBX SDK wheel is `cp310` only. The pod's active interpreter is 3.11, so
   the wheel can never install there. LAM is a Python 3.10 project.
3. `thirdparties.tar` (1.16 GB) and `LAM_human_model.tar` never extracted: tar
   fails with "Cannot change ownership" on the RunPod network filesystem, which
   broke the `tar && rm` chain. Use `tar --no-same-owner`.

Also: `huggingface-cli` is renamed to `hf`; the old name silently prints help
instead of downloading. And `numpy==1.23.0` in requirements.txt is unsatisfiable
on 3.11 (pandas needs >=1.23.2) — on 3.10 the original pin is fine.

## State on /workspace (persists across pod stop)

- `/workspace/LAM` — repo, `model_zoo` 3.2 GB (LAM-20K weights), `thirdparties`
  2.0 GB, `assets` incl. `sample_oac/{animation.glb,template_file.fbx}`.
- `/workspace/software/blender-4.0.2-linux-x64/blender` — Blender executable.
- `/workspace/v310` — Python 3.10 venv, created but **install incomplete**:
  stage3 was cut off during torch cu121 download.
- `/workspace/ref_frontal_v1.jpg` — reference portrait, sha256
  `826135bf938fa6b23416e61ab8672aedafab1b7f57119f7cd447ee69213a3e70`.
- Setup scripts `/root/lam_stage{2,3}.sh`, logs `/workspace/stage*.log`.

Note: `/root` is container disk and is WIPED on stop. Only `/workspace` survives.
Everything above is on `/workspace` except the stage scripts — recreate those.

## Next steps, in order

1. Resume pod, re-read SSH port, rerun `/root/lam_stage3.sh` content from the
   venv step onward (torch 2.3.0 cu121, requirements.txt, fbx cp310 wheel,
   `external/landmark_detection/FaceBoxesV2/utils/make.sh`).
2. Verify: `python -c "import torch,fbx,pandas"` and `torch.cuda.is_available()`.
3. Run inference on `ref_frontal_v1.jpg` with `enable_oac_file` true and
   `--blender_path /workspace/software/blender-4.0.2-linux-x64/blender`.
   Output lands in `./output/open_avatar_chat/<id>.zip`.
4. Pull the zip to the VPS, publish via file vault, open in the avatar client
   with `?renderer=lam&model=<share url>`.
5. STOP THE POD as soon as the zip exists.

## Budget

Started at $2.35. Roughly $0.60 spent through setup. Remaining balance leaves
under two hours of pod time — not enough for a debugging loop on the export
step. Top up before resuming, or expect to stop mid-run.

## Deployed and working already (no pod needed)

VRM vertical slice is live and hits 60 FPS on iPhone:
`https://ebridge-ui.178-105-43-79.sslip.io/avatar-3b7ac3c9e6f4f3d3297b735c/`
Served from `/var/lib/eiros/avatar-client`, built out of the worktree
`.worktrees/realtime-lam-avatar`, nginx location in `ebridge-ui.conf`.
Not merged to main — blocked behind the unresolved merge gate.

Fixes made this session, still only in that worktree, not committed:
- `client-mode.ts` / `main.ts` — model paths now respect the deployment base.
- `renderer.ts` — aspect-aware camera framing, `?view=head|bust|full`.
- `vrm-adapter.ts` + `renderer.ts` — `setLean` added; body lean was computed by
  the behavior engine every frame and silently discarded, so the body never
  moved. Breath scale raised from 0.6% to 2.8%.
- `behavior-engine.ts` — idle amplitudes roughly doubled, second harmonic added.
- Tests 31/31 green. COMMIT THESE — they exist only as working-tree edits.

## Open, needs Rico

- Merge gate still unenforced (`merge_gate_not_enforced_2026_08_24`). Two agent
  votes for the queue_claim-lease fix, awaiting his call.
- 10-minute physical iPhone acceptance run on the VRM slice never done.
- Photo upload from the browser UI: requested, not started. Vault upload
  endpoint `/vault-ui-<token>/api/upload` works and is the intended transport.
