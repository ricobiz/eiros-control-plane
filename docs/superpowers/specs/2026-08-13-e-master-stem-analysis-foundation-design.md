# E-MASTER Stem Analysis Foundation Design

## Purpose

Add a four-stem diagnostic layer to E-MASTER so a problem detected by Track Stress, MIC LOOP, or normal mastering analysis can be attributed to the musical source that is creating the load instead of only to a frequency band in the full mix.

The first version is analysis-only. It must never alter the uploaded source or rebuild the master from separated stems.

## User-visible outcome

For any analyzed excerpt, E-MASTER can report contributions such as:

- `63–90 Hz: BASS 61% · DRUMS 35% · OTHER 4%`
- `2.8–4.0 kHz: VOCALS dominant`
- `hot window 92.5–96.0 s: DRUMS + BASS are the primary contributors`

When Track Stress or MIC LOOP identifies a suspect time/frequency region, the same report can attach stem attribution to that finding.

## Scope

### Included

- Four stems only: `drums`, `bass`, `vocals`, `other`.
- Demucs separation using the maintained PyPI package and its four-stem model path.
- Separation in a dedicated worker environment, independent of E-MASTER's serving virtualenv.
- CPU-only execution on the current VPS.
- Exactly one separation job at a time.
- Cached, deterministic stem artifacts keyed to source identity plus separation configuration.
- Analysis of each stem with the existing E-MASTER NumPy/FFmpeg analysis primitives.
- Time-window and frequency-band contribution maps.
- Attribution API consumable by Director, Track Stress, and MIC LOOP.
- Failure must degrade to normal full-mix E-MASTER analysis rather than block mastering.

### Explicitly not included

- Stem-aware EQ/compression/rendering.
- Re-summing separated stems into the delivery master.
- Six-stem separation.
- REAPER automation.
- Matchering reference mastering.
- Essentia integration.
- Pedalboard/VST3 integration.
- Any automatic artistic decision solely because one stem dominates a band.

Those are separate later projects after this diagnostic layer proves useful.

## Dependency strategy

### Demucs

Demucs is the only new audio engine required by this project. It runs outside the main E-MASTER Python environment so PyTorch/Torchaudio dependencies cannot destabilize the public MCP/API service.

The worker uses one fixed model/configuration for a given cache version. Model name, Demucs package version, sample rate, segment setting, and output format are written into the separation manifest.

### Deferred libraries

Essentia, Pedalboard, and Matchering are intentionally not dependencies of this phase. Their licensing and/or resource requirements are evaluated separately before they can become product dependencies.

## Current VPS constraints

The current preview host has:

- 2 x86_64 CPU cores.
- About 3.7 GiB RAM.
- No NVIDIA GPU.
- No swap.

Therefore the worker must:

- run one separation process at a time;
- use CPU mode explicitly;
- use one worker thread/process by default;
- use Demucs segmentation to cap peak memory;
- expose timeout and failure state;
- never run inside the MCP request handler process;
- never restart or block the production 8792 service.

Before full-track separation is enabled, implementation must benchmark one 20-second real E-MASTER excerpt and record wall time and peak RSS. If the process cannot stay within a safe host budget, the feature remains excerpt-only on this host and the architecture preserves a future remote-worker boundary.

## Architecture

### 1. Stem worker boundary

A focused worker module owns separation execution. The public E-MASTER process requests a job and reads its result; it does not import Demucs or Torch.

The boundary is intentionally file/job based:

`E-MASTER source -> stem job manifest -> worker subprocess -> four WAV stems + result manifest`

This allows the worker to move to another VPS/GPU later without changing Director or analysis semantics.

### 2. Stem cache

Stem outputs live under the mastering data root in an isolated subtree, for example:

`stem_cache/<asset_id>/<separation_fingerprint>/`

The fingerprint includes at minimum:

- source content identity;
- Demucs package version;
- model name;
- four-stem mode;
- segment configuration;
- requested source range for excerpt jobs.

A valid cache entry contains all four stems plus a manifest. Partial outputs are never treated as valid.

### 3. Stem analysis

Each stem is analyzed independently using E-MASTER's current digital analysis primitives. The first version computes only descriptors needed for attribution:

- short-window RMS/energy;
- robust peak level;
- E-MASTER frequency bands;
- optional finer logarithmic stress bands;
- timeline windows aligned across all four stems.

No high-level semantic ML descriptors are required in this phase.

### 4. Contribution map

For each aligned time window and frequency band, E-MASTER calculates each stem's relative energy contribution.

The result stores both absolute digital level and normalized contribution. A dominant stem is a diagnostic statement about the separated representation, not a claim that the stem is defective.

Example shape:

```json
{
  "start_seconds": 92.5,
  "end_seconds": 93.5,
  "band": "bass_60_120",
  "contributors": {
    "bass": {"level_dbfs": -15.2, "share": 0.61},
    "drums": {"level_dbfs": -17.6, "share": 0.35},
    "vocals": {"level_dbfs": -41.0, "share": 0.00},
    "other": {"level_dbfs": -27.9, "share": 0.04}
  },
  "dominant_stem": "bass"
}
```

Shares are derived from linear energy, not directly from dB values.

### 5. Track Stress integration

A Track Stress suspect has a time range and one or more frequency bands. Stem attribution intersects that region with the contribution map and returns:

- top contributing stems;
- contribution shares;
- confidence/availability state;
- separation manifest identity.

Track Stress ranking remains based on the full mix. Stem attribution explains the load; it does not replace the stress detector.

### 6. MIC LOOP integration

MIC LOOP remains an acoustic comparison of physical playback recordings. Stem attribution never analyzes microphone recordings as stems.

When MIC LOOP produces a valid suspect frequency/time region, E-MASTER looks up the corresponding digital source/master excerpt and attaches stem contributors from that region.

This keeps acoustic evidence and digital source attribution as independent evidence layers.

### 7. Director integration

Director receives stem attribution as evidence, for example:

`problem band 60–120 Hz; contributors bass=0.61, drums=0.35`

In this phase Director may explain the likely source of the issue but may not generate stem-specific DSP actions. Existing full-mix actions remain unchanged.

## Job lifecycle

A stem job has explicit states:

- `PENDING`
- `RUNNING`
- `READY`
- `FAILED`

A failed or timed-out job records an error code and bounded diagnostic text. API consumers can continue without stems.

Duplicate requests for the same fingerprint reuse a READY cache entry or the existing active job instead of spawning another Demucs process.

## Safety and operational behavior

- Never mutate uploaded source files.
- Never overwrite ordinary masters.
- Never launch more than one Demucs process on the current VPS.
- Never allow a web request to wait indefinitely for Demucs.
- All generated stem files are diagnostic derivatives.
- The preview service on port 8800 is the only deployment target during development.
- Production port 8792 is not restarted or promoted by this project.
- Existing headless MCP behavior remains unchanged.

## Testing strategy

### Unit tests

Use synthetic aligned stems to verify:

- energy shares sum to approximately 1 for active bands;
- a bass-heavy stem dominates a bass band;
- a drum transient can dominate a short hot window without dominating the whole excerpt;
- dB values are converted to linear energy before share calculation;
- missing/failed stem data returns unavailable attribution rather than false certainty.

### Worker contract tests

Use a fake executable/fixture to verify:

- job fingerprinting;
- cache reuse;
- partial output rejection;
- timeout/failure states;
- single-job lock behavior;
- manifest versioning.

### Real smoke benchmark

After the isolated Demucs environment is installed, run exactly one 20-second excerpt from an existing E-MASTER asset before enabling full tracks. Record:

- model/configuration;
- wall-clock time;
- peak RSS;
- resulting stem files;
- attribution result for at least one bass-heavy band.

The benchmark is a deployment gate, not merely informational logging.

## Success criteria

The first version is successful when:

1. A real 20-second E-MASTER excerpt can be separated into four cached stems without destabilizing the preview service.
2. E-MASTER can return a time/frequency contribution map for those stems.
3. A Track Stress or MIC LOOP suspect region can be decorated with stem contributors without changing its original classification.
4. Failure or unavailability of Demucs does not prevent ordinary mastering, calibration, or playback.
5. The public in-chat MCP panel remains disabled/headless.

## Follow-on projects

After this layer is validated on real tracks:

1. **DSP execution foundation:** evaluate Pedalboard or another permissively acceptable backend for deterministic plugin/effect execution.
2. **Reference mastering:** evaluate Matchering as an isolated optional worker; current host memory is insufficient for safe co-location without resource changes.
3. **Advanced MIR:** evaluate Essentia only after an explicit licensing decision.
4. **DAW bridge:** evaluate REAPER MCP for workstation/session workflows, not as a dependency of headless mastering.
5. **Stem-aware mastering:** only after separation artifacts and contribution reliability are quantified; never assume Demucs stems are transparent enough to re-sum blindly.
