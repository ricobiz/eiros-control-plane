# Realtime LAM Avatar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an official LAM Gaussian renderer backend to the existing avatar client and prove it can be driven by the current canonical AvatarFrame runtime.

**Architecture:** Keep VRM untouched. Add a small LAM adapter translating canonical face/state into callbacks for `gaussian-splat-renderer-for-lam`, select backend at runtime, and validate with the official evaluation asset plus browser smoke tests.

**Tech Stack:** TypeScript, Vite, Vitest, existing Three.js/three-vrm client, `gaussian-splat-renderer-for-lam`.

**Spec:** `docs/superpowers/specs/2026-08-28-realtime-lam-avatar-design.md`

## Global Constraints
- Do not remove or regress the existing VRM backend.
- Do not change canonical AvatarFrame for renderer-specific fields.
- Treat official LAM-weight-generated assets as non-commercial evaluation assets.
- Do not create/delete extra RunPod Pods automatically.
- TDD for adapter/state behavior; browser smoke for WebGL integration.

---

### Task 1: LAM expression/state adapter
- Create `avatar-client/src/lam-expression-adapter.test.ts` first and verify RED.
- Implement `avatar-client/src/lam-expression-adapter.ts` mapping canonical blink/jaw/smile channels plus chat state and interrupt semantics.
- Verify targeted and full tests; commit.

### Task 2: Official Gaussian renderer wrapper
- Add `gaussian-splat-renderer-for-lam` dependency.
- Create renderer-independent unit tests for wrapper lifecycle/callback ownership.
- Implement `avatar-client/src/lam-renderer.ts` with lazy import and explicit start/dispose boundary.
- Verify tests/build; commit.

### Task 3: Evaluation fixture and selectable client
- Copy official sample `p2-1.zip` into `public/models/lam-eval.zip` with provenance note.
- Add `?renderer=lam` selection while keeping default VRM.
- Drive local simulator into LAM callback, add Idle/Listening/Thinking/Responding controls and interrupt.
- Verify full tests/build; commit.

### Task 4: Browser/mobile smoke
- Serve production build.
- Headless Chromium at 390x844 must load the LAM asset with zero console/page errors and report active LAM status/FPS.
- Record evidence in `docs/REALTIME_AVATAR_V0.md`; commit.

### Task 5: User reconstruction when GPU is available
- Start existing RunPod only; no new Pod.
- Install LAM persistently under `/workspace/LAM`, download official assets/weights, stage user portrait and run reconstruction/export.
- Collect result to VPS, stop GPU, replace evaluation fixture only after the result is validated.
