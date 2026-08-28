# Realtime LAM Avatar Renderer Design

## Goal
Prove that the existing renderer-neutral EIROS AvatarFrame/Behavior runtime can drive a photorealistic LAM Gaussian avatar in a mobile browser without changing the brain, transport, interruption, or timing architecture.

## Scope
This is an evaluation/prototype layer. Keep the existing VRM renderer intact as a fallback. Add LAM as a second renderer backend using the official `gaussian-splat-renderer-for-lam` package and an official sample LAM asset until a user-specific reconstruction can be produced on RunPod.

## License boundary
LAM source code is Apache-2.0 and LAM_WebRender is MIT. The official LAM model weights are governed by `LICENSE_WEIGHT`, Creative Commons Attribution-NonCommercial 4.0. Therefore generated/evaluation assets from those weights are prototype-only until a commercially permitted reconstruction backend or separate license is selected.

## Architecture
`AvatarFrame -> FacialMixer/Behavior -> LamExpressionAdapter -> GaussianSplatRenderer`.

The LAM adapter exposes the callbacks expected by the official renderer:
- `getExpressionData()` returns current ARKit-compatible weights.
- `getChatState()` maps EIROS interaction state to the renderer's Idle/Listening/Thinking/Responding state.

The canonical protocol does not change. Renderer selection is client-side. VRM and LAM consume the same session state.

## Vertical Slice
- Bundle one official sample LAM avatar as an evaluation fixture.
- Add a LAM renderer page/backend without deleting VRM.
- Drive eye blink, jaw, smile and state changes from deterministic local AvatarFrame data.
- Provide an interrupt control that immediately zeros speech-owned mouth channels and transitions to Listening.
- Verify production build and real browser WebGL load at iPhone viewport.
- Measure FPS in the same acceptance HUD.

## RunPod Reconstruction
The user portrait is staged separately. Reconstruct with LAM-20K when the existing RTX 4090 Pod is available. Do not create or delete an extra paid Pod automatically. Export the resulting LAM ZIP and replace only the renderer asset; do not change AvatarFrame or Behavior Engine.

## Success Criteria
- LAM sample renders with zero browser console errors.
- >=30 FPS target on the available iPhone-sized browser smoke environment; actual physical iPhone remains final acceptance.
- Blink/jaw/smile changes are visibly/semantically applied through ARKit callback data.
- Interrupt does not require renderer recreation.
- VRM backend still builds/tests.
