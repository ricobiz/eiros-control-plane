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
- Bass-only prototype for v0.
- User starts playback with an explicit tap, satisfying iOS audio gesture requirements.
- The test presents one controlled tone at a time instead of requiring the user to catch a continuous sweep boundary.
- Output starts at a conservative digital level and never jumps to full scale.
- Two primary responses are enough for boundary finding:
  - green `OK` = this test point is still acceptable / clean
  - red `NO` = this test point is already unacceptable / weak / distorted / otherwise past the useful boundary
- Optional compact reason chips may classify a red response after the fact (`weak`, `distort`, `too strong`) without interrupting the main flow.
- The engine changes one test dimension at a time and keeps the last known-good point and first known-bad point.
- Once both sides of a boundary are known, the next test point is chosen between them (binary/adaptive search) until the interval is sufficiently narrow.
- The same boundary is rechecked from the opposite direction or with a repeated nearby point before it is considered confirmed.
- A confirmed result records the good/bad bracket, estimated critical point or interval, repeatability, and confidence.

### Test dimensions
The prototype must support the same adaptive-bracketing mechanism for:
1. **Frequency boundary** — at a fixed conservative digital level, find the lowest/highest or otherwise critical frequency where the current playback chain stops being acceptable.
2. **Level boundary** — at a fixed frequency, increase/decrease digital test level in conservative steps to find the highest acceptable level before audible degradation or discomfort.

Only one dimension changes during a single search. Frequency and level are never changed simultaneously while estimating a boundary.

### Controls
Keep the interface intentionally small:
- Start / Stop
- current frequency
- current digital test level
- green `OK`
- red `NO`
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
For the prototype, calibration state may remain local to the page. Preserve the raw decision sequence, not only the final boundary, so later we can look for repeatable patterns and eventually automate parts of calibration.

A result contains:
- profile/test version
- test dimension (`frequency` or `level`)
- fixed dimension value used during the search
- ordered test points with frequency, digital level, `OK`/`NO`, optional reason, and timestamp
- last known-good point
- first known-bad point
- verification points
- confirmed boundary or interval
- repeatability/confidence
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
2. Start tap reliably produces the requested test tone.
3. `OK` advances the search farther into the tested direction while preserving the last known-good point.
4. `NO` establishes or tightens the bad side of the bracket.
5. Once both sides are known, subsequent test points converge between them until the interval is sufficiently narrow.
6. A verification pass repeats/reverses around the candidate boundary and reports repeatability/confidence.
7. The same mechanism can run for a frequency boundary and for a digital-level boundary while changing only one dimension at a time.
8. Stop/page hide silences audio immediately.
9. Repeated start/stop/retest cycles do not create multiple oscillators or accumulating timers.
10. Raw `OK`/`NO` decisions are retained locally for later pattern analysis.
11. No ChatGPT card is mounted and the conversation remains unaffected.

## Deferred
- Full-range calibration
- L/R tests
- loudness-threshold maps
- monitor-only corrective EQ
- saved named headphone/device profiles
- assistant-visible calibration context
- integration into the final fullscreen E-MASTER workstation
