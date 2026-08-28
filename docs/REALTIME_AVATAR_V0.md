# Realtime Avatar V0

## What this slice proves

The browser owns rendering of a rigged VRM avatar. Canonical timestamped avatar frames drive facial expressions, head pose, gaze and breathing. Procedural blink/gaze/head/breath behavior remains alive independently of incoming speech motion. `interrupt` clears queued speech animation without stopping idle behavior.

## Run

```bash
cd avatar-client
npm install
npm run dev -- --host 0.0.0.0
```

The default model slot is `avatar-client/public/models/avatar.vrm`. A different `.vrm` can be selected with the file picker or `?model=<url>`.

## Custom appearance

The supplied portrait is the appearance target. The runtime is deliberately independent of how the final rigged asset is authored. A single portrait does not contain the unseen geometry, topology, body, teeth, tongue or ARKit/VRM facial rig required for an exact 3D reconstruction, so V0 does not pretend that the portrait itself is already a finished avatar asset.

## Mobile acceptance

Run the page on the target iPhone for 10 continuous minutes and record:

- rendered frame rate: target >= 30 FPS;
- timeline/audio drift: target absolute drift < 40 ms and no accumulating trend;
- interrupt: queued mouth/speech motion disappears visually in < 200 ms;
- idle: blink, gaze micro-motion, head micro-motion and breathing continue after interrupt;
- model load: missing expression channels degrade without a runtime crash.

The HUD shows rolling FPS and maximum observed local timeline drift. V0 uses a local deterministic transport; LiveKit and Audio2Face are intentionally the next integration layer, not hidden inside the renderer.

## Verified acceptance evidence — 2026-08-28

- Vitest: 9 test files, 18 tests passed.
- Production TypeScript/Vite build: exit 0.
- Python repository baseline: 62 passed, 1 skipped.
- Headless Chromium mobile viewport: 390×844.
- Default bundled VRM parsed successfully: `Live · 20 face channels`.
- Browser console/page errors: none.
- Headless software-rendered smoke HUD observed: `35 FPS · 0 ms` after model load. This is a functional smoke number, not a substitute for the required 10-minute physical-iPhone acceptance run.
