# Realtime VRM Avatar v0 Design

## Goal

Build the first end-to-end, phone-visible avatar vertical slice for EIROS: one custom female character based on the supplied visual reference, rendered as a rigged VRM/GLB avatar in the browser and controllable in real time through a renderer-neutral avatar state protocol.

This slice proves that the character can feel alive before integrating the full speech/LLM stack.

## Scope

The first slice includes:

- one realistic/stylized-realistic humanoid avatar derived from the supplied visual reference;
- browser renderer based on Three.js and `@pixiv/three-vrm`;
- normalized humanoid rig;
- facial expression control through a canonical expression layer;
- eye gaze;
- blinking;
- head yaw/pitch/roll;
- subtle idle head motion;
- breathing/upper-body idle motion;
- jaw/mouth opening and basic mouth shape controls;
- spring-bone simulation for hair where the avatar asset supports it;
- timestamped remote avatar-state frames;
- a small interpolation buffer so motion remains smooth under network jitter;
- realtime command controls for testing the avatar from a remote controller;
- mobile browser validation, with iPhone Safari as the primary target.

This slice does **not** include:

- MuseTalk as the realtime renderer;
- Audio2Face integration;
- LLM-driven autonomous behavior;
- speech recognition;
- streaming TTS;
- Gaussian/NeRF avatar rendering;
- automated character factory;
- full-body locomotion or a large animation library;
- production identity reconstruction from a single photo.

Those components remain compatible follow-on layers behind the protocol defined here.

## Character Asset Strategy

The supplied photo is the visual identity reference, not a complete 3D scan. A single image cannot uniquely determine hidden geometry, profile shape, ears, scalp, rear hair volume, or body proportions.

For v0, the asset pipeline must therefore produce a **plausible rigged interpretation** of the reference rather than claiming one-to-one biometric reconstruction.

The first asset should preserve the visibly important characteristics:

- adult female appearance;
- long voluminous wavy blonde hair;
- light skin;
- green/light eyes;
- full lips;
- strong eyebrows;
- realistic human facial proportions;
- black/dark clothing for the initial presentation.

The asset must be exportable as VRM 1.0 or GLB with a compatible humanoid rig. The browser runtime must not depend on the exact authoring tool used to create it.

## Architecture

The browser owns rendering. The server/controller sends compact semantic animation state, never prerendered avatar video.

```text
Remote controller / later EIROS runtime
        |
        | AvatarFrame + reliable commands
        v
TransportReceiver
        v
TimelineBuffer
        v
BehaviorMixer
        v
AvatarMorphMapper
        v
VRMRenderer (Three.js + three-vrm)
        v
Browser / iPhone GPU
```

The first implementation may use WebSocket transport for the local vertical slice if this shortens time-to-proof. The transport interface must remain abstract so LiveKit Data can replace it without changing renderer or behavior code.

## Canonical Avatar State

The renderer consumes one normalized state regardless of the source system:

```ts
export interface AvatarFrame {
  version: 1;
  sequence: number;
  framePtsMs: number;
  audioPtsMs?: number;
  face: Partial<Record<CanonicalFaceChannel, number>>;
  head: {
    yaw: number;
    pitch: number;
    roll: number;
  };
  gaze: {
    x: number;
    y: number;
  };
  body: {
    breath: number;
    lean: number;
  };
  state?: {
    listening?: number;
    speaking?: number;
    emotion?: string;
    attention?: string;
  };
}
```

Values are normalized and clamped by the client. Face channels use a canonical naming layer rather than direct VRM expression names.

## Face Mapping

VRM models differ in available morph targets. The runtime therefore has an `AvatarMorphMapper` between canonical face channels and the loaded model.

For v0, required channels are:

- `jawOpen`;
- `mouthSmileLeft` / `mouthSmileRight` when available;
- `mouthFunnel` or closest available mouth-rounding expression;
- `eyeBlinkLeft` / `eyeBlinkRight`;
- brow raise if available.

Missing optional morphs must degrade gracefully. A model that cannot blink or open its mouth fails the asset validation gate.

Later, Audio2Face's ARKit-compatible output can feed the same canonical layer without changing renderer code.

## Behavior Mixer

The first client includes lightweight procedural behavior so the avatar is visibly alive even when no remote commands arrive.

Procedural layers:

- randomized blink generator;
- small eye saccades;
- slow gaze drift with return-to-center behavior;
- subtle head spring/noise;
- breathing oscillator;
- idle upper-body lean;
- expression smoothing.

Remote commands override or bias these generators rather than replacing the entire state.

Examples:

```text
look_left
look_right
look_at_camera
nod
head_left
head_right
blink
smile
mouth_open
mouth_close
```

The implementation exposes a small debug panel so each action can be triggered manually from the browser during validation.

## Timeline and Jitter Handling

Incoming frames are timestamped. The renderer does not apply network frames immediately. It samples from a short interpolation window.

Initial target:

- interpolation delay: 60-100 ms;
- stale frames are dropped rather than replayed;
- sequence gaps do not block rendering;
- renderer interpolates head, gaze, breath, and face values between the two nearest states;
- reliable commands are handled separately from animation frames.

This is intentionally compatible with a later LiveKit design in which animation updates may be lossy/unordered while control commands remain reliable.

## Renderer

The renderer uses:

- TypeScript;
- Vite;
- Three.js;
- `@pixiv/three-vrm`;
- WebGL initially, with WebGPU considered only after baseline mobile compatibility is measured.

Responsibilities:

- load VRM/GLB asset;
- normalize avatar scale/camera framing;
- update VRM expression manager;
- update look-at or eye bones;
- apply normalized head rotation;
- update spring bones;
- render at display refresh cadence;
- report FPS and frame-time statistics in debug mode.

No speech/LLM-specific logic is allowed inside the renderer.

## Transport

Define a transport interface:

```ts
export interface AvatarTransport {
  connect(): Promise<void>;
  close(): void;
  onFrame(handler: (frame: AvatarFrame) => void): () => void;
  onCommand(handler: (command: AvatarCommand) => void): () => void;
}
```

v0 can provide:

- `MockTransport` for deterministic tests and demos;
- `WebSocketTransport` for remote control from the VPS.

A future `LiveKitTransport` must implement the same interface.

## Asset Validation Gate

Before accepting an avatar asset, the app checks:

- model loads without exception;
- humanoid head bone exists;
- both eyes can be addressed or the model supplies a working look-at system;
- blink controls exist;
- mouth opening or speech mouth control exists;
- spring-bone update does not throw if present;
- model remains within a mobile-oriented triangle/texture budget chosen after the first phone FPS measurement.

The reference depicts an adult. Future catalog/factory work must separately enforce age and identity-similarity review; that policy is outside this runtime slice.

## UI

The v0 page is intentionally simple and evaluation-focused:

- full-screen avatar viewport;
- minimal dark background/studio lighting;
- compact debug drawer that can be hidden;
- buttons/sliders for gaze, head, blink, smile, jaw, breath;
- connection indicator;
- FPS/frame-time readout;
- asset status/error message.

The default view should be visually presentable enough to judge whether continuing the avatar project is worthwhile. It should not look like an engineering wireframe when the debug drawer is closed.

## Error Handling

- Invalid/missing model: show explicit asset error instead of blank canvas.
- Missing optional morph: log capability downgrade and continue.
- Missing required blink/mouth control: fail asset validation.
- Transport disconnect: avatar continues procedural idle locally and shows disconnected status.
- Out-of-order/stale frame: drop it; never rewind the avatar.
- NaN/out-of-range values: clamp or discard before applying to the rig.

## Testing

Unit tests cover:

- frame validation and clamping;
- interpolation;
- stale/out-of-order frame handling;
- canonical morph mapping;
- behavior generators staying within bounds;
- transport event subscription/unsubscription.

Browser smoke tests cover:

- app loads;
- avatar asset loads;
- debug controls change visible avatar state;
- transport disconnect does not freeze rendering.

Manual mobile acceptance covers a 10-minute run on iPhone Safari.

## Definition of Done

The vertical slice is complete when:

1. The custom reference-based avatar loads in the browser with a stable identity and presentable appearance.
2. With debug UI hidden, the avatar continuously breathes, blinks, performs small eye/head idle movement, and does not look frozen.
3. Manual or remote commands can turn the head, change gaze, blink, smile, and open/close the mouth in real time.
4. Hair/secondary motion reacts where the asset provides spring bones.
5. The same state path works through `MockTransport` and remote `WebSocketTransport`.
6. On target iPhone Safari, the page maintains at least 30 FPS for 10 minutes without progressive memory growth or animation drift.
7. A transport interruption does not freeze the character; local idle behavior continues.
8. The architecture exposes stable extension points for later LiveKit, Audio2Face, TTS, and EIROS behavior integration without rewriting the renderer.
