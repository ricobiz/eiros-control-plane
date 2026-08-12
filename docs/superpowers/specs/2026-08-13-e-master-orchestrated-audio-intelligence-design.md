# E-MASTER Orchestrated Audio Intelligence — Design

**Date:** 2026-08-13  
**Status:** Approved for implementation planning  
**Product name:** E-MASTER

## Goal

E-MASTER should be the decision-making and orchestration layer for mastering, not a monolithic reimplementation of mature audio tooling. The first implementation phase adds **4-stem analysis only** so E-MASTER can identify which musical component is responsible for a problematic frequency/time region without altering or remixing stems.

The target flow is:

`ANALYZE → STEM ATTRIBUTION → MASTER PLAN → DIGITAL AUDIT → MIC LOOP / TRACK STRESS → VERIFY → LEARN MONITOR PROFILE`

## Core principle

External engines provide evidence or execute bounded DSP. **E-MASTER remains the authority that interprets evidence, constructs the mastering plan, verifies the result, and learns monitoring trust.**

No external engine may silently apply artistic changes to the export master. Source audio is preserved.

## Phase 1 scope: 4-stem analysis only

Use a mature source-separation engine directly from the backend to split the uploaded source into four analysis stems:

- `drums`
- `bass`
- `vocals`
- `other`

These stems are **diagnostic derivatives**, not replacement mix stems. They are never substituted into the final master in Phase 1.

For each stem and the original full mix, E-MASTER computes aligned time/frequency evidence so it can answer questions such as:

- Which stem dominates a suspicious 63–90 Hz region?
- Is a low-frequency overload mainly bass, kick/drums, or their combination?
- Is a 2–5 kHz anomaly primarily vocal, drums, or other material?
- Which stem is active at the exact Track Stress / MIC LOOP failure window?
- Does the source already contain the suspect feature before mastering?

## Architecture

### 1. E-MASTER Core

Existing E-MASTER remains the control plane and owns:

- source asset identity and preservation;
- section-aware analysis;
- Director mastering plans;
- deterministic render execution;
- post-render digital artifact audit;
- Track Stress calibration;
- MIC LOOP physical playback-chain evidence;
- verification and profile persistence.

The new stem subsystem is called by E-MASTER Core and returns structured evidence only.

### 2. Stem Separation Adapter

Create a narrow internal adapter around the chosen separation engine. Initial model contract is four stems only.

Input:

- source asset path;
- requested model/version;
- optional analysis excerpt range.

Output:

- paths for `drums`, `bass`, `vocals`, `other`;
- source hash;
- separation-engine version/model;
- sample rate/channels/duration;
- separation runtime metadata;
- quality/error flags.

The adapter boundary must allow the separation engine to be replaced later without changing Director or calibration code.

### 3. Stem Feature Analysis

For every stem, compute the same aligned evidence grid used for full-mix reasoning. Minimum Phase 1 features:

- short-window RMS / energy;
- robust peak energy;
- log-frequency-band energy;
- activity ratio / persistence;
- contribution by band and time window;
- normalized contribution relative to the full mix;
- basic transient/crest evidence where useful.

The initial implementation may reuse existing NumPy/FFmpeg analysis where reliable. A mature feature library may later replace or cross-check individual descriptors behind the same internal interface.

### 4. Stem Attribution Model

Given a time range and frequency range, return a ranked contribution report.

Example contract:

```json
{
  "window": {"start_seconds": 92.5, "end_seconds": 112.5},
  "band": {"low_hz": 60, "high_hz": 120},
  "contributors": [
    {"stem": "bass", "share": 0.61},
    {"stem": "drums", "share": 0.35},
    {"stem": "other", "share": 0.03},
    {"stem": "vocals", "share": 0.01}
  ],
  "confidence": 0.88,
  "source_only": true
}
```

Percent/share values are analytical contribution estimates, not claims of perceptual loudness or physical SPL.

### 5. Integration with Track Stress

When Track Stress identifies a limiting frequency band/window, E-MASTER requests stem attribution for that exact region.

Result should let Director state:

- limiting band;
- active source stems;
- dominant contributor;
- whether multiple stems overlap strongly enough that a full-mix intervention would be risky;
- whether the suspect energy is transient or persistent.

No stem processing occurs automatically in Phase 1.

### 6. Integration with MIC LOOP

MIC LOOP remains a physical playback-chain test. Stem analysis applies to the **digital source/master window corresponding to the physical failure**, not to the microphone recording itself.

If MIC LOOP reports a repeatable problem around a specific time/frequency region and the digital render audit is clean, E-MASTER can annotate the physical limitation with the musical contributor:

`playback-chain stress at 70 Hz → bass dominant, drums secondary`

This does not imply that the bass stem is defective; it means that material from that stem is the principal source of load in the failing region.

### 7. Director behavior

Director consumes stem attribution as evidence. It may use that evidence to avoid destructive broad corrections.

Example:

- full-mix analysis says 70 Hz is excessive;
- stem attribution says `bass 63%, drums 33%`;
- kick/drums are otherwise healthy;
- Director should avoid a broad low-band cut that unnecessarily weakens the kick.

In Phase 1 Director may recommend or parameterize a safer full-mix action, but it may not render per-stem processing.

## External-engine strategy

### Source separation

Use a mature separation engine directly through an internal adapter rather than adopting an entire third-party MCP server. This keeps dependency surface small and gives E-MASTER ownership of storage, versioning, retry logic, and evidence formatting.

### Feature analysis

A mature analysis library can be introduced behind `StemFeatureAnalyzer` when it materially improves descriptors. Existing NumPy/FFmpeg analysis remains acceptable for simple measurements. E-MASTER interfaces must not depend on one specific analysis library.

### DSP execution

Phase 1 does not change the current mastering executor. A plugin-capable DSP layer can be introduced later behind an executor abstraction. It must never bypass Director verification.

### Reference mastering

Reference matching is a separate optional mode. It may provide comparative evidence or a proposed target, but it does not replace Director and is not part of Phase 1 stem implementation.

### External reference catalog

Catalog/search MCPs can later provide professional reference candidates and licensed stems where available. They are a **reference-source layer**, not the source-separation solution for arbitrary user uploads.

### DAW integration

REAPER/MCP integration is deliberately deferred. It is useful for future workstation mode, routing, plugin automation, and session-level rendering, but it is not required for headless Phase 1 analysis.

## Data model

Add a versioned stem-analysis record associated with an asset, never embedded destructively into the source file.

Minimum record fields:

- schema version;
- asset id and source hash;
- separation engine/model/version;
- created timestamp;
- four stem derivative identities;
- feature-analysis version;
- per-stem timeline/band descriptors;
- quality flags;
- attribution-query results may be cached by time/band key.

Derived stem audio should be stored separately from export masters and clearly marked diagnostic.

## Failure handling

Separation failure must not block ordinary E-MASTER mastering.

Possible states:

- `STEM_READY`
- `STEM_PENDING`
- `STEM_UNAVAILABLE`
- `STEM_DEGRADED`

If separation fails, Director falls back to full-mix evidence and reports that stem attribution is unavailable. Never invent a contributor.

If a stem contains obvious separation artifacts or low-confidence bleed, attribution confidence must be reduced rather than treating the stem as ground truth.

## Performance and caching

Separation is expensive, so it should be performed once per source hash/model/version and cached.

For live calibration, E-MASTER should reuse existing stem derivatives and analyze only the requested short window when possible.

Do not rerun separation for every Track Stress step or MIC LOOP recording.

## Safety and product boundaries

- Stem analysis is diagnostic evidence, not a claim about listener hearing or medical hearing ability.
- MIC LOOP remains a monitoring/playback-chain experiment, not calibrated SPL/THD metrology.
- No calibration profile may automatically EQ the export master to compensate for listener hearing or headphone limitations.
- Phase 1 never rebuilds the final mix from separated stems.
- Source files are immutable.

## User-facing behavior

The first UI exposure can be compact. When a problem region exists, show a ranked attribution such as:

`60–120 Hz · BASS 61% · DRUMS 35% · OTHER 3% · VOCALS 1%`

The user does not need a full stem mixer in Phase 1.

An optional diagnostic player may later solo stems for inspection, but that is not required for the first implementation.

## Testing strategy

### Separation adapter tests

- correct four-stem contract;
- deterministic cache key from source hash + model/version;
- missing/failed engine returns a degraded state without breaking mastering;
- source remains unchanged.

### Attribution tests

Use synthetic mixtures with known contributors so tests can prove:

- a bass-only 63 Hz component is attributed primarily to `bass`;
- a kick-like low-frequency component from `drums` is distinguishable from sustained bass;
- mixed contributors return proportional rankings;
- inactive stems do not receive fabricated contribution.

### Integration tests

- Track Stress suspect band/window returns stem attribution;
- MIC LOOP physical failure can attach digital stem attribution only after digital audit passes;
- ordinary mastering still works with stem subsystem disabled/unavailable;
- no Phase 1 code path renders a final master from separated stems.

## Implementation order

1. Preserve and finish the currently in-progress MIC LOOP seal-normalization fix independently.
2. Add the stem-separation adapter and cache contract.
3. Add four-stem feature analysis.
4. Add time/frequency attribution queries.
5. Connect attribution to Track Stress.
6. Connect attribution annotations to MIC LOOP results.
7. Add compact API/UI exposure.
8. Validate on existing E-MASTER source assets before considering any stem-aware processing.

## Deferred work

Not included in Phase 1:

- per-stem mastering or remixing;
- 6-stem models;
- automatic vocal/beat rebalance;
- REAPER workstation execution;
- VST3/Audio Unit plugin automation;
- automatic reference matching;
- automatic reference-catalog selection;
- rebuilding masters from separated stems.

These are separate design/implementation phases after Phase 1 evidence quality is validated.

## Success criteria

Phase 1 is successful when E-MASTER can take an existing uploaded song, generate/cached four diagnostic stems, and for any requested Track Stress or MIC LOOP problem region return a believable, confidence-scored ranking of which stems contribute to that region — while the standard mastering path remains unchanged and operational.
