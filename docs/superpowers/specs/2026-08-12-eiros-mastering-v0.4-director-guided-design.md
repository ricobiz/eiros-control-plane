# EIROS Mastering v0.4 — Director-Guided Mastering with Verification Loop

## Purpose

EIROS Mastering v0.4 is not an autonomous mastering preset system. It is an AI-directed mastering workstation in which deterministic DSP performs measurement and execution, while the conversational intelligence acts as mastering director.

The core rule is simple: **the engine may measure and execute, but it must not make untraceable artistic decisions.**

The system must preserve intentional characteristics even when they appear statistically unusual. A sub-heavy ritual track, for example, must not have its low end reduced merely because the analyzer classifies the spectral balance as atypical.

## Design goals

1. Preserve artistic intent before conforming to generic mastering norms.
2. Make every DSP action traceable to an explicit reason.
3. Support section-aware and time-local decisions instead of one global preset.
4. Re-analyze every rendered master and compare it directly with the source.
5. Refuse to mark a render FINAL until post-master verification passes.
6. Provide a visual control panel that exposes source, master, deltas, metadata, actions, and verification state.
7. Produce clean exports with optional metadata stripped deterministically.
8. Learn from prior mastering decisions and Rico's feedback without blindly replaying settings.
9. Keep DSP deterministic, testable, and independent from the reasoning layer.
10. Preserve source audio unchanged and retain reproducible render provenance.

## Non-goals

- Building a fully autonomous mastering service that guesses artistic intent.
- Letting an LLM manipulate raw PCM sample-by-sample.
- Training a black-box model directly on prior masters in v0.4.
- Replacing human/AI artistic review with LUFS, spectral targets, or genre presets.
- Automatically applying historical settings only because a new track has similar numeric features.

## System architecture

### 1. Audio Forensics layer

The first stage is read-only analysis. It must never alter audio.

It produces:

- source format, sample rate, bit depth, codec, duration;
- integrated LUFS, short-term loudness, loudness range, RMS, sample peak, true peak;
- crest factor and transient-density timeline;
- waveform overview and section boundaries;
- frequency-energy distribution over time, not only whole-track averages;
- dominant-frequency and spectral-centroid timelines;
- stereo correlation, phase/coherence, M/S balance where available;
- DC offset;
- clipping, near-clipping, inter-sample risk, and possible codec damage indicators;
- suspicious resonances and persistent narrow-band buildup;
- low-end concentration and low-end stability;
- section trajectory classification: rising, falling, stable, transition;
- metadata/container audit.

The analyzer reports observations, not prescriptions. For example:

- valid observation: `20–60 Hz contains 49% of measured spectral energy`;
- invalid autonomous conclusion: `reduce 20–60 Hz by 1 dB`.

### 2. Artistic Intent Context

Every mastering job has an explicit context object. It can be generated from the conversation, entered through the panel, or both.

Example fields:

- intended emotional effect;
- critical elements to preserve;
- elements allowed to change;
- elements explicitly protected from automatic correction;
- preferred loudness/impact range;
- dynamics philosophy;
- stereo philosophy;
- reference tracks or prior approved masters when available;
- known defects reported by Rico;
- export target such as streaming, soundtrack, archive, or private listening.

The context object is advisory to the director layer and constraining to the renderer when converted into a master plan.

### 3. Eiros Director layer

The conversational intelligence receives:

- artistic intent context;
- compact whole-track analysis;
- section map;
- anomaly list;
- source/master history where applicable;
- relevant experience-memory matches.

It returns a structured **Master Plan** rather than raw DSP code.

The director decides whether a measured feature is:

- intentional and protected;
- neutral;
- suspicious and worth testing;
- definitely defective and eligible for correction.

It must prefer the smallest justified intervention.

### 4. Master Plan

A Master Plan is a deterministic, inspectable set of instructions.

Each action must contain:

- `scope`: global or time range;
- `processor`: EQ, dynamic EQ, gain, compression, transient shaping, saturation, M/S, stereo width, declip, limiter, etc.;
- `parameters`;
- `reason`;
- `confidence`;
- `maximum_allowed_change`;
- `protected_features` relevant to that action;
- `expected_effect`;
- optional `rollback_condition`.

Example conceptual action:

```json
{
  "scope": {"start": 92.0, "end": 118.0},
  "processor": "dynamic_eq",
  "parameters": {"frequency_hz": 63, "max_reduction_db": 0.6},
  "reason": "localized resonance appears only in the dense section",
  "confidence": 0.83,
  "maximum_allowed_change": {"sub_band_mean_db": 0.7},
  "protected_features": ["global sub weight", "kick transient"],
  "expected_effect": "remove local bloom without reducing the track's intentional bass mass"
}
```

The engine must reject malformed or unsupported actions rather than approximating them silently.

### 5. Deterministic DSP renderer

The renderer is deliberately non-creative.

Responsibilities:

- validate the Master Plan;
- apply only supported processors;
- enforce per-action maximum-change constraints;
- preserve source timing unless explicitly changed;
- render reproducibly;
- write a machine-readable action log;
- preserve the original uploaded source unchanged;
- emit 48 kHz / 24-bit WAV by default where technically appropriate;
- optionally create clean MP3 derivatives from the approved WAV master.

The renderer must not introduce additional EQ, compression, gain riding, or stereo processing that is absent from the plan, except hard safety constraints explicitly documented in the render provenance.

### 6. Post-Master Inspector

Every render is re-analyzed from scratch.

The inspector compares source vs master globally and section-by-section and produces a **Delta Map**.

Required comparisons include:

- LUFS and loudness-range delta;
- sample and true-peak delta;
- crest-factor delta;
- transient-density and transient-amplitude delta;
- spectral energy delta by band and over time;
- narrow-band resonance changes;
- stereo correlation and phase delta;
- M/S distribution delta where available;
- clipping and inter-sample risk;
- limiter gain-reduction statistics;
- dynamic processing activity by section;
- unexpected silence, truncation, timing drift, or channel changes;
- export format and metadata verification.

The inspector must distinguish **expected changes** described by the Master Plan from **unexpected changes**.

### 7. Verification gate

A render has the following state progression:

`SOURCE → ANALYZED → DIRECTED → RENDERED → VERIFIED → APPROVED`

`APPROVED` is only possible after post-master inspection.

Automatic hard failures include at minimum:

- true-peak violation;
- clipping introduced by mastering;
- unexpected channel/layout change;
- corrupted or truncated output;
- metadata-cleaning failure when clean export was requested;
- action exceeding its declared maximum allowed change;
- significant unplanned stereo-correlation collapse;
- unplanned large crest-factor loss;
- unplanned large protected-band change.

Soft warnings are presented to the director for judgment. The director may accept them only with an explicit reason that becomes part of provenance.

Failed verification returns the job to:

`VERIFIED_FAILED → DIRECTED_REVISION → RENDERED → VERIFIED`

No failed render may be labeled FINAL.

## Candidate workflow

The director may request multiple candidate masters from the same source and analysis without re-uploading the source.

Recommended default candidate family:

- **Preserve** — minimal intervention, maximum source character;
- **Impact** — stronger transient/loudness presentation while respecting protected features;
- **Cinematic** — preserves macro-dynamics and spatial depth.

Candidates are not presets with fixed settings. They are distinct strategies generated for the specific track.

Each candidate receives its own Master Plan, render provenance, Delta Map, verification result, and Rico feedback.

## Visual mastering panel

The MCP panel is the visual control surface for the system. It is not the mastering intelligence.

### Core views

#### Source / Master / Delta

One synchronized timeline with selectable overlays:

- SOURCE waveform;
- MASTER waveform;
- DELTA view;
- section boundaries;
- loudness trajectory;
- crest/transient trajectory;
- stereo correlation;
- limiter/compressor activity;
- per-band spectral energy.

Clicking a time region must show exactly what processing occurred there and why.

Example:

`01:32–01:48 · Dynamic EQ · 63 Hz · max −0.6 dB · reason: local resonance · verified delta: −0.31 dB mean`

#### Spectral comparison

- source spectrum;
- master spectrum;
- delta spectrum;
- selectable whole track or selected section;
- no decorative smoothing that hides real changes.

#### Metrics

Display real measured data for both source and master:

- LUFS;
- LRA;
- true peak;
- RMS;
- crest factor;
- stereo correlation;
- major band-energy percentages;
- metadata state;
- verification status.

#### Master Plan inspector

Show every action with:

- time scope;
- processor;
- settings;
- reason;
- confidence;
- expected effect;
- measured result;
- pass/warn/fail state.

#### A/B playback

Provide synchronized source/master playback with matched audition gain so "louder" is not mistaken for "better".

The panel should additionally allow raw-level playback where requested.

### Metadata / clean export view

The panel must show all detected optional metadata before export, including where technically available:

- ID3 tags;
- RIFF INFO;
- BWF/BEXT;
- XMP;
- comments;
- encoder/library tags;
- cover art;
- chapters;
- arbitrary application tags;
- other optional container metadata.

Clean export removes all optional metadata by default while retaining only what is technically mandatory for a valid audio file.

The UI must show:

- what was detected;
- what will be removed;
- what was actually removed;
- post-export verification that those fields are absent.

The system must never claim that an unknown proprietary audio watermark has been removed unless it can explicitly detect and remove it.

## Experience Memory

Experience Memory improves future reasoning but never acts as an autonomous preset database.

### Stored record

For every approved or explicitly rejected candidate, store a compact record containing:

- anonymous or local track fingerprint;
- measured feature summary;
- section archetypes;
- artistic-intent summary;
- protected features;
- anomalies considered;
- Master Plan actions and reasons;
- post-master Delta Map summary;
- verification result;
- Rico feedback;
- director judgment about why the candidate succeeded or failed;
- final approval state.

Raw source audio is not required for Experience Memory unless explicitly enabled separately.

### Retrieval

For a new track, memory retrieval returns similar **situations**, not settings to auto-apply.

Example retrieval:

`Three prior bass-dominant ritual/cinematic tracks had intentional 20–60 Hz dominance. Preserving sub weight while using only local resonance control was approved in 3/3 cases.`

The director may use this as evidence, reject it, or request a candidate that tests the historical pattern.

### Learning hierarchy

Experience should be categorized by confidence:

1. **Rico-approved** — strongest preference evidence for Rico's own mastering aesthetic;
2. **Rico-rejected** — strong negative evidence;
3. **Verified technical lesson** — repeatable technical outcome independent of taste;
4. **Director hypothesis** — useful but unconfirmed;
5. **Generic mastering prior** — weakest and always subordinate to track-specific intent.

Memory must preserve the distinction between subjective preference and technical correctness.

## Provenance and reproducibility

Every render stores:

- source asset ID and source hash;
- analysis version;
- director-plan version;
- renderer version;
- every processing action and parameter;
- render target format;
- post-analysis version;
- verification result;
- clean-export report;
- timestamps;
- candidate label;
- approval/rejection feedback.

A previously approved master must be reproducible from its source and Master Plan when processor versions remain available.

## Error handling

- Unsupported DSP action: reject plan before render.
- Analysis failure: no mastering attempt.
- Render failure: preserve source and previous candidates; report exact stage.
- Post-analysis failure: render remains `UNVERIFIED`, never FINAL.
- Verification failure: retain candidate for diagnosis but prevent approval until explicitly revised or overridden with recorded reason.
- Metadata-clean verification failure: output remains non-final.
- Memory subsystem failure: mastering may continue without memory; the failure must be visible and must not alter DSP behavior.

## Testing strategy

### Unit tests

- Master Plan schema validation;
- maximum-change enforcement;
- metadata scanner and cleaner;
- source/master delta calculations;
- verification thresholds;
- state-machine transitions;
- memory record serialization and retrieval filtering.

### Golden audio tests

Maintain a small local corpus with known properties:

- sub-dominant intentional mix;
- harsh high-frequency mix;
- clipped mix;
- wide/phase-risk mix;
- dynamic cinematic mix;
- already-good source needing nearly no processing.

The tests verify that the engine does not "correct" protected artistic features without a plan action.

### Regression test from Ayibobo

`Ayibobo` becomes a canonical regression case for the architectural failure that motivated v0.4.

Expected behavior:

- analyzer may report extreme low-frequency dominance;
- no low-frequency cut is applied merely because of that observation;
- if sub is protected in artistic intent, any low-band change must be explicitly justified and bounded;
- post-verification must flag unexpected sub loss;
- a generic adaptive decision like the v0.3 behavior must fail this regression test.

### A/B verification tests

- source/master playback remains sample-synchronized;
- matched-gain A/B does not introduce clipping;
- displayed metrics match backend measurements;
- timeline action annotations match actual renderer instructions.

## Migration from v0.3

The current adaptive engine remains available temporarily as a legacy/reference mode but is no longer the recommended mastering path.

The new primary flow becomes **Director-Guided**.

Migration order:

1. Add Master Plan schema and renderer execution boundary.
2. Add source/master Delta Map and post-verification state machine.
3. Disable autonomous spectral correction in the Director-Guided path.
4. Add visual action/verification overlays to the panel.
5. Expand metadata audit and deterministic clean-export verification.
6. Add Experience Memory records and retrieval.
7. Add multi-candidate workflow.
8. Keep legacy adaptive only for A/B comparison until Director-Guided is stable.

## Acceptance criteria for v0.4

v0.4 is considered complete when:

1. A source can be uploaded and analyzed without modification.
2. A structured Master Plan can be created and validated.
3. The renderer performs only actions defined by that plan plus declared hard-safety operations.
4. The same source can produce multiple candidate strategies.
5. Every candidate is re-analyzed automatically.
6. Source/master Delta Maps are available globally and by section.
7. Verification can block a technically or artistically out-of-bounds render from becoming FINAL.
8. The panel displays real source/master/delta metrics and processing actions.
9. Clean export strips optional metadata and verifies the result.
10. Experience Memory stores approved/rejected decisions with context and can retrieve similar prior situations without auto-applying them.
11. `Ayibobo` no longer loses intentional low-end mass merely because the analyzer considers it statistically dominant.
12. Every final approved master has complete provenance and a post-verification pass.

## Architectural invariant

**No DSP action without a traceable reason. No FINAL master without post-render verification. No statistical anomaly may be treated as a defect until artistic intent says it is one.**

## Professional Workstation UI Amendment

The MCP panel is a first-class mastering workstation, not a thin control surface. Its design goal is the clarity, immediacy, and visual authority of professional mastering software while remaining optimized for ChatGPT-hosted interaction.

### UI principles

- The visual hierarchy must make the current mastering state obvious within one glance: source, analysis, director plan, render, verification, approval.
- The interface must be dark, restrained, information-dense, and cinematic without decorative noise.
- Core information must be visible before controls. Controls should appear only where they correspond to a clear mastering decision.
- Every DSP action shown in the UI must be traceable to a reason and a time/frequency scope.
- The panel must feel alive during analysis and rendering: timeline progress, active section highlighting, meter movement, analysis status, render status, and verification state should update coherently rather than through generic spinners.
- Mobile/iOS rendering is a hard requirement. The panel must collapse intelligently without turning into an unreadable desktop UI squeezed into a phone.

### Main workstation layout

1. **Transport / source strip**
   - Source name, codec, duration, sample rate, bit depth, file size.
   - Play/pause, seek, current time, duration.
   - Source/Master/Delta audition selector.
   - A/B loudness-matched audition mode.

2. **Master timeline**
   - Waveform overview.
   - Section boundaries and trajectory labels.
   - Per-section status markers: untouched, planned, processed, flagged, verified.
   - Overlay lanes for gain, dynamic EQ, compression/limiter activity, detected issues, and verification failures.
   - Clicking a section opens the exact Director decision, reason, DSP parameters, and source/master delta for that section.

3. **Analysis workspace**
   - Real measured LUFS, true peak, LRA, RMS, crest factor, stereo correlation, DC offset.
   - Spectrum and band-energy view.
   - Spectrogram or time-frequency heatmap when available.
   - Stereo/phase view.
   - Transient density / crest timeline.
   - Clipping, overs, resonance and suspicious-artifact markers.

4. **Director plan view**
   - Human-readable artistic intent.
   - Explicit protected traits, e.g. `preserve sub mass`, `preserve crescendo`, `do not widen choir`.
   - Per-section actions with reason, scope, strength and hard bounds.
   - Candidate strategy selector: Preserve / Impact / Cinematic / custom Director candidate.
   - No opaque "adaptive" action may appear without an explainable Director plan entry.

5. **Render / Delta view**
   - Source versus Master spectrum delta.
   - Loudness and crest delta by time.
   - Gain reduction and limiter activity timeline.
   - Stereo correlation delta.
   - Per-band and per-section change summaries.
   - Every visible change links back to the Director decision that caused it.

6. **Post-master verification view**
   - Verification status: PASS / REVIEW / REJECTED.
   - Exact failed checks, affected time ranges and severity.
   - Automatic rerender history and what changed between attempts.
   - FINAL/APPROVED export is impossible until verification passes and the Director approves.

7. **Metadata and clean-export view**
   - Enumerate container metadata, ID3/RIFF/BWF/XMP/comments, embedded art, chapters and encoder-identifying fields when detectable.
   - Distinguish required structural fields from optional metadata.
   - Show exactly what will be removed.
   - Clean export strips optional metadata and does not claim removal of proprietary acoustic watermarks that cannot be reliably detected or removed.

8. **Experience Memory view**
   - Show relevant prior mastering cases as contextual evidence, never as automatic rules.
   - Display similarity reason, prior decision, QA outcome and Rico approval/rejection.
   - Allow accepted/rejected outcomes to become experience records.
   - Experience is advisory to the Director; it never bypasses Director reasoning or verification.

### Professional interaction requirements

- No dashboard-card clutter for primary audio work. Timeline, waveform, spectrum and delta views are the dominant surfaces.
- Metrics use compact strips and contextual overlays rather than large decorative tiles.
- Controls must be labeled with audio meaning, not implementation jargon.
- Dangerous actions such as delete, destructive metadata removal from originals, or output replacement require explicit confirmation; source audio is immutable.
- Rendering must always create a new revision so comparisons remain possible.
- The panel must expose revision history and allow immediate A/B comparison between source and every candidate/master revision.
- Visual styling must remain consistent across desktop browser, ChatGPT web, and ChatGPT iOS embedding.

### UI acceptance criteria

- A user can understand what the system changed, where it changed it, and why without reading logs or raw JSON.
- A user can audition Source, Master and loudness-matched A/B from the same transport.
- A user can click any processed section and see its Director reasoning and exact DSP delta.
- Verification failures are visible on the timeline at the affected time range.
- Metadata slated for removal is explicitly listed before clean export.
- The workstation remains usable at 320 CSS px width and scales cleanly to desktop width.
- The UI does not present the automatic DSP engine as the decision maker; the Director plan is the authority shown to the user.
