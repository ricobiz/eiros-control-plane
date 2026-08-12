# E-MASTER Calibration Test Design

## Goal
Prove that the calibration interaction works reliably on iPhone/browser before returning any in-chat MCP UI.

The first calibration prototype is deliberately tiny: it tests the real playback path, lets Rico mark an audible critical boundary, and rechecks that boundary automatically.

## Product role
E-MASTER is primarily a collaborative mastering workstation used together with the assistant, with optional semi-automatic and automatic modes. Calibration creates a listening profile for the current playback chain so mastering decisions can distinguish track problems from monitoring limitations.

Calibration is NOT a claim to measure the physical headphone frequency response without measurement hardware. It records practical audible boundaries for the current listener + device + headphones chain.

## First prototype scope

### Surface
A standalone browser route on the existing E-MASTER v17 preview server. It is not registered as an MCP Apps resource and must not create a ChatGPT card/iframe.

### Test
- Bass sweep only for v0.
- User starts playback with an explicit tap, satisfying iOS audio gesture requirements.
- A sine tone sweeps through a bounded bass range.
- Output starts at a conservative digital level and never jumps to full scale.
- Current frequency is visible.
- Three compact mark buttons:
  - `↓` = becomes too weak / disappears
  - `!` = distortion, rattle, buzz, or other artifact
  - `↑` = subjectively too strong
- On mark, the test stores frequency, direction, timestamp, and event kind.
- The test then performs a slower local verification pass around the marked frequency.
- A confirmed boundary is shown as a compact result with an estimated interval and confidence.

### Controls
Keep the interface intentionally small:
- Start / Stop
- current frequency
- one minimal sweep indicator
- `↓ ! ↑`
- Retest
- Reset

No technical mastering metrics belong on this screen.

## Safety
- Require explicit user interaction to begin audio.
- Use conservative gain with short fade-in/fade-out ramps to prevent clicks and sudden level changes.
- Never increase the device's hardware volume.
- Show a short instruction to begin with low headphone volume.
- Stop audio immediately on page hide/unload and when Stop is pressed.

## Data model
For the prototype, calibration state may remain local to the page. A result contains:
- profile/test version
- test band
- event kind
- first-pass frequency
- verification frequencies
- confirmed boundary or interval
- confidence
- created timestamp

Persistent multi-device listening profiles are explicitly deferred until the playback prototype is proven stable.

## Architecture
- Existing E-MASTER mastering backend remains unchanged and headless.
- Add one lightweight standalone calibration HTML route to the v17 preview service.
- Generate tone client-side with Web Audio API; do not stream audio from the server.
- Do not attach `_meta.ui.resourceUri`, `openai/outputTemplate`, or any widget resource to this test.
- No polling, SSE, WebSocket, waveform decoding, or large payloads.

## Success criteria
1. Opens on iPhone through the v17 preview HTTPS origin.
2. Start tap reliably produces the test tone.
3. Frequency sweep is smooth and audible.
4. Mark buttons capture the current frequency correctly.
5. Verification pass revisits a narrow range around the mark.
6. Stop/page hide silences audio immediately.
7. Repeated start/stop/retest cycles do not create multiple oscillators or accumulating timers.
8. No ChatGPT card is mounted and the conversation remains unaffected.

## Deferred
- Full-range calibration
- L/R tests
- loudness-threshold maps
- monitor-only corrective EQ
- saved named headphone/device profiles
- assistant-visible calibration context
- integration into the final fullscreen E-MASTER workstation
