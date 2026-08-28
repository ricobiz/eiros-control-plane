# Realtime VRM Avatar V0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a mobile-browser vertical slice where one custom-target VRM avatar renders continuously and can be driven in realtime for head pose, gaze, blink, breathing, facial expression, and mouth movement.

**Architecture:** A standalone TypeScript/Vite client owns Three.js + `@pixiv/three-vrm`. A canonical `AvatarFrame` enters through a transport-neutral receiver, is time-buffered/interpolated, mixed with procedural behavior, mapped onto VRM expressions/bones, and rendered. V0 includes a local deterministic simulator so the whole avatar runtime is testable before LiveKit/A2F are connected.

**Tech Stack:** TypeScript, Vite, Three.js, `@pixiv/three-vrm`, Vitest, browser WebGL with WebGPU kept as a later renderer option.

**Spec:** `docs/superpowers/specs/2026-08-28-realtime-vrm-avatar-v0-design.md`

## Global Constraints

- V0 must run in mobile Safari and desktop Chromium.
- The renderer must not depend on MuseTalk, LivePortrait, Gaussian rendering, Audio2Face, ASR, TTS, or LLM.
- Server-facing state remains renderer-neutral and uses canonical avatar parameters.
- Missing avatar expressions must degrade gracefully rather than crash.
- Procedural idle behavior runs independently from incoming speech/mouth frames.
- No production LiveKit changes are required for V0; the transport boundary must be ready for a later LiveKit adapter.
- The supplied portrait is an appearance target, not sufficient source material for exact unseen 3D geometry; V0 runtime work must not claim exact identity reconstruction.

---

### Task 1: Avatar client scaffold and deterministic runtime types

**Files:**
- Create: `avatar-client/package.json`
- Create: `avatar-client/tsconfig.json`
- Create: `avatar-client/vite.config.ts`
- Create: `avatar-client/index.html`
- Create: `avatar-client/src/avatar-frame.ts`
- Create: `avatar-client/src/avatar-frame.test.ts`

**Interfaces:**
- Produces: `AvatarFrame`, `FaceState`, `HeadState`, `GazeState`, `BodyState`, `clampAvatarFrame(frame)`.

- [ ] Write tests that construct canonical frames and verify clamping of face weights, gaze, breath, and normalized quaternion fallback.
- [ ] Run `npm test -- --run src/avatar-frame.test.ts` and verify failure before implementation.
- [ ] Implement the exact canonical types and pure clamping/normalization function.
- [ ] Run the test and verify pass.
- [ ] Commit `feat(avatar): scaffold canonical avatar runtime`.

### Task 2: Timeline buffer and interpolation

**Files:**
- Create: `avatar-client/src/timeline-buffer.ts`
- Create: `avatar-client/src/timeline-buffer.test.ts`

**Interfaces:**
- Consumes: `AvatarFrame`.
- Produces: `TimelineBuffer.push(frame)`, `TimelineBuffer.sample(audioPtsMs)` and `TimelineBuffer.clear()`.

- [ ] Write tests for out-of-order rejection, bounded queue length, linear interpolation of scalar face/gaze/body values, and quaternion interpolation behavior.
- [ ] Run targeted test and verify failure.
- [ ] Implement an 80 ms presentation-delay buffer with monotonic sequence handling and interpolation.
- [ ] Run targeted test and verify pass.
- [ ] Commit `feat(avatar): add realtime timeline buffer`.

### Task 3: Procedural behavior and facial mixer

**Files:**
- Create: `avatar-client/src/behavior-engine.ts`
- Create: `avatar-client/src/behavior-engine.test.ts`
- Create: `avatar-client/src/facial-mixer.ts`
- Create: `avatar-client/src/facial-mixer.test.ts`

**Interfaces:**
- Produces: `BehaviorEngine.tick(nowMs, dtMs)` returning blink, gaze micro-motion, head micro-motion and breath; `mixFace(speechFace, behaviorFace, emotionFace)`.

- [ ] Write deterministic seeded tests for blink lifecycle, breathing bounds, gaze bounds, idle head offsets, and ownership rules where speech dominates jaw/mouth while behavior dominates blink/look channels.
- [ ] Run targeted tests and verify failure.
- [ ] Implement seeded procedural generators and channel-aware additive mixer with clamping.
- [ ] Run targeted tests and verify pass.
- [ ] Commit `feat(avatar): add procedural behavior mixer`.

### Task 4: VRM adapter and graceful morph mapping

**Files:**
- Create: `avatar-client/src/vrm-adapter.ts`
- Create: `avatar-client/src/vrm-adapter.test.ts`

**Interfaces:**
- Consumes: canonical mixed `AvatarFrame` plus a VRM-like expression/bone facade.
- Produces: `VrmAdapter.apply(frame)` and `VrmAdapter.capabilities()`.

- [ ] Write mock-based tests proving known expressions are applied, absent ARKit-style morphs are skipped, head quaternion reaches normalized head bone, gaze reaches look-at/fallback eye bones, and breath reaches upper-chest/spine offset without throwing.
- [ ] Run targeted test and verify failure.
- [ ] Implement a capability-discovering mapper with aliases for common VRM expression names and safe no-op fallbacks.
- [ ] Run targeted test and verify pass.
- [ ] Commit `feat(avatar): map canonical state onto VRM rigs`.

### Task 5: Three.js/three-vrm renderer and local avatar simulator

**Files:**
- Create: `avatar-client/src/renderer.ts`
- Create: `avatar-client/src/simulator.ts`
- Create: `avatar-client/src/main.ts`
- Create: `avatar-client/src/style.css`
- Create: `avatar-client/public/models/README.md`

**Interfaces:**
- Consumes: VRM URL and canonical frames.
- Produces: a full-screen avatar page, FPS readout, runtime state readout, and local controls for head/gaze/smile/mouth/blink plus an automatic idle demo.

- [ ] Add unit tests for simulator frame sequence/timestamps and renderer-independent state transitions.
- [ ] Run tests and verify failure.
- [ ] Implement GLTF/VRM loading, camera/light/resize loop, spring-bone update through VRM update, simulator controls, and continuous behavior tick.
- [ ] Run tests and `npm run build`; verify both pass.
- [ ] Commit `feat(avatar): render realtime VRM vertical slice`.

### Task 6: Transport boundary and interruption semantics

**Files:**
- Create: `avatar-client/src/transport.ts`
- Create: `avatar-client/src/transport.test.ts`
- Modify: `avatar-client/src/main.ts`

**Interfaces:**
- Produces: `AvatarTransport` interface, `LocalTransport`, reliable `AvatarCommand` handling, and `interrupt()` semantics that clear queued speech mouth motion while leaving idle behavior alive.

- [ ] Write tests proving stale lossy frames do not block newer frames, reliable interrupt clears speech state immediately, and procedural blink/breath continues after interrupt.
- [ ] Run targeted tests and verify failure.
- [ ] Implement transport-neutral interface and local adapter; do not add LiveKit dependency yet.
- [ ] Run tests and build.
- [ ] Commit `feat(avatar): define realtime avatar transport boundary`.

### Task 7: Mobile acceptance harness and documentation

**Files:**
- Create: `avatar-client/src/perf-monitor.ts`
- Create: `avatar-client/src/perf-monitor.test.ts`
- Create: `docs/REALTIME_AVATAR_V0.md`
- Modify: `avatar-client/src/main.ts`

**Interfaces:**
- Produces: rolling FPS/frame-time metrics and visible acceptance indicators.

- [ ] Write tests for rolling FPS/frame-time calculations and threshold state.
- [ ] Run targeted tests and verify failure.
- [ ] Implement metrics overlay and document exact mobile acceptance procedure: 10-minute run, >=30 FPS target, no accumulating timeline drift, visible interrupt reaction target <200 ms.
- [ ] Run complete `avatar-client` tests and production build.
- [ ] Commit `test(avatar): add mobile acceptance harness`.

### Task 8: Whole-slice verification

**Files:**
- Modify only if verification exposes a defect in files owned by Tasks 1-7.

**Interfaces:**
- Consumes the complete V0 client.
- Produces evidence that unit tests and production build pass and the static app can be served for phone testing.

- [ ] Run `npm test -- --run`.
- [ ] Run `npm run build`.
- [ ] Start Vite preview bound to an externally reachable interface and smoke-test the page from the VPS itself.
- [ ] Record exact verification evidence in `docs/REALTIME_AVATAR_V0.md`.
- [ ] Commit verification-only fixes/docs if needed.
