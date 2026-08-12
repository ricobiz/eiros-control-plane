# EIROS Mastering v0.4 Workstation UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current generic panel with a responsive professional mastering workstation centered on transport, waveform/timeline, source-master-delta analysis, Director reasoning, verification, metadata cleanup, and revision audition.

**Architecture:** Split the current 99 KB inline panel in `runtime/mastering_mcp_server.py` into a dedicated HTML/CSS/JS workstation resource while preserving MCP embedding and HTTP APIs. The UI is read-heavy and timeline-first: audio surfaces dominate; metrics and controls remain contextual. It consumes the v0.4 core APIs defined in the companion core plan and never invents DSP decisions client-side.

**Tech Stack:** HTML5, CSS, vanilla JavaScript, Canvas/SVG, native Audio element/Web Audio only where browser policy permits, FastMCP UI resource, Starlette APIs. No React/build pipeline is required for v0.4.

## Global Constraints

- The UI must remain usable from 320 CSS px through desktop widths.
- ChatGPT iOS embedding is a release requirement, not a best-effort target.
- Source audio is immutable and visually distinguished from generated revisions.
- Source/Master/Delta and A/B audition share one transport state.
- Timeline is the primary surface; do not build a grid of decorative dashboard cards.
- Every displayed DSP change must link to a Director reason.
- Verification failures must be visible at their exact timeline range.
- The client never decides mastering parameters; it displays/requests Director-approved plans only.
- Existing share/download behavior must remain available.

---

### Task 1: Extract the panel from the MCP server and lock UI contracts

**Files:**
- Create: `runtime/mastering_panel_v17.html`
- Create: `runtime/test_mastering_panel_v17.py`
- Modify: `runtime/mastering_mcp_server.py`

**Interfaces:**
- `mastering_panel_resource()` reads a dedicated resource file and injects only stable endpoint/base configuration.
- Panel consumes `/api/list`, `/api/analyze`, v0.4 Director/verify endpoints, source and output audio endpoints.

- [ ] **Step 1: Write failing resource tests**

Assert panel v17 contains semantic anchors: `workstation`, `transport`, `master-timeline`, `director-plan`, `verification`, `metadata-audit`, `revision-list`.

- [ ] **Step 2: Extract current panel into `mastering_panel_v17.html` without visual redesign yet**

Make this a behavior-preserving extraction first. Keep existing upload/list/download functionality operational.

- [ ] **Step 3: Change MCP panel resource to load v17 file**

Keep v16 legacy resource available until release acceptance.

- [ ] **Step 4: Run panel tests and compile MCP server**

Run:

```bash
python3 -m pytest runtime/test_mastering_panel_v17.py -v
python3 -m py_compile runtime/mastering_mcp_server.py
```

- [ ] **Step 5: Commit**

```bash
git add runtime/mastering_panel_v17.html runtime/mastering_mcp_server.py runtime/test_mastering_panel_v17.py
git commit -m "refactor: extract mastering workstation panel"
```

---

### Task 2: Build professional workstation shell and responsive layout

**Files:**
- Modify: `runtime/mastering_panel_v17.html`
- Modify: `runtime/test_mastering_panel_v17.py`

**Interfaces:**
- Produces DOM regions: top transport strip, main timeline, analysis dock, Director drawer, verification drawer, revision rail.

- [ ] **Step 1: Add structural UI tests**

Assert no primary audio surface is nested in repeated generic `.card` containers; assert responsive CSS includes 320 px handling and desktop breakpoint.

- [ ] **Step 2: Implement restrained studio visual system**

Use a near-black neutral background, one accent color for active/selected state, typography with tabular numeric metrics, subtle separators, no gradients/glows except minimal meter emphasis. Do not emulate a specific proprietary DAW.

- [ ] **Step 3: Implement responsive workstation layout**

Desktop: transport header, full-width timeline, lower split between analysis and Director/QA. Mobile: transport -> timeline -> tabbed analysis/Director/QA -> revisions; no horizontal page scroll.

- [ ] **Step 4: Verify keyboard/focus and touch target behavior**

Native buttons/selects, visible focus, >=44 px touch targets for primary transport controls on iOS.

- [ ] **Step 5: Commit**

```bash
git add runtime/mastering_panel_v17.html runtime/test_mastering_panel_v17.py
git commit -m "feat: add professional mastering workstation layout"
```

---

### Task 3: Implement unified Source/Master/Delta transport and loudness-matched A/B

**Files:**
- Modify: `runtime/mastering_panel_v17.html`
- Modify: `runtime/mastering.py` only if a server-side gain-matched preview endpoint is required
- Modify: `runtime/mastering_mcp_server.py` only if endpoint wiring is required
- Create: `runtime/test_mastering_ab_transport.py`

**Interfaces:**
- One current-time model controls all audition sources.
- Selector values: `source`, `master:<output_id>`, `delta:<output_id>`.
- A/B mode compensates preview level so loudness does not bias comparison.

- [ ] **Step 1: Write A/B synchronization tests for server preview metadata**

Ensure source/master previews expose matching duration/timebase and explicit loudness-match gain values.

- [ ] **Step 2: Implement transport state machine in JS**

Switching source/master must preserve playback position within 50 ms where browser timing permits.

- [ ] **Step 3: Implement loudness-match toggle**

Use measured source/master integrated loudness difference; clamp preview-only compensation to a safe range. Never alter downloaded master.

- [ ] **Step 4: Add visible mode/status labels**

Always show whether audition is SOURCE, MASTER, DELTA, and whether LOUDNESS MATCH is active.

- [ ] **Step 5: Commit**

```bash
git add runtime/mastering_panel_v17.html runtime/mastering.py runtime/mastering_mcp_server.py runtime/test_mastering_ab_transport.py
git commit -m "feat: add mastering source master ab transport"
```

---

### Task 4: Build the master timeline with waveform, sections, actions, and QA flags

**Files:**
- Modify: `runtime/mastering_panel_v17.html`
- Create: `runtime/test_mastering_timeline_payload.py`
- Modify: `runtime/mastering_mcp_server.py` if timeline payload endpoint is needed

**Interfaces:**
- Timeline payload includes normalized waveform envelope, section bounds, Director action ranges, verification flags, limiter/gain-reduction lane data.

- [ ] **Step 1: Define and test compact timeline payload**

Target payload shape:

```json
{
  "duration": 243.4,
  "waveform": [[0.0, 0.12], [0.1, 0.18]],
  "sections": [{"start": 57.5, "end": 74.5, "status": "verified"}],
  "actions": [{"start": 60.0, "end": 66.0, "type": "dynamic_eq", "action_id": "act_62hz_control_001"}],
  "flags": [{"start": 92.0, "end": 94.5, "severity": "review", "code": "crest_delta"}]
}
```

- [ ] **Step 2: Render waveform and section lanes on Canvas**

Keep SVG/DOM labels for accessibility and click targets.

- [ ] **Step 3: Add synchronized playhead and scrub**

Timeline click/touch seeks the audio transport. Playhead updates through `requestAnimationFrame` while playing.

- [ ] **Step 4: Add action and QA overlays**

Clicking an overlay opens exact Director reason, requested/applied parameters, and verification delta.

- [ ] **Step 5: Test resize behavior at 320, 390, 736 and 1200 CSS px**

Automated DOM/CSS tests plus manual browser/iOS verification during execution.

- [ ] **Step 6: Commit**

```bash
git add runtime/mastering_panel_v17.html runtime/mastering_mcp_server.py runtime/test_mastering_timeline_payload.py
git commit -m "feat: add interactive mastering timeline"
```

---

### Task 5: Build analysis, spectrum, stereo and delta views from real measurements

**Files:**
- Modify: `runtime/mastering_panel_v17.html`
- Modify: `runtime/mastering.py` if additional measured series are required
- Create: `runtime/test_mastering_analysis_payload.py`

**Interfaces:**
- Analysis payload exposes only real measured values; no client-generated pseudo-metrics.

- [ ] **Step 1: Add tests for measured analysis payload**

Required fields: LUFS, TP, LRA, RMS, crest, stereo correlation, DC, band percentages, section metrics, source/master delta metrics.

- [ ] **Step 2: Implement compact numeric meter strip**

Use tabular values and status indicators instead of large metric cards.

- [ ] **Step 3: Implement spectrum and delta spectrum**

Plot measured band/time-frequency data. Source and Master must be distinguishable; Delta must be a signed change view.

- [ ] **Step 4: Implement stereo/phase and crest/transient timeline views**

If full vectorscope data is not available in v0.4 core, render measured correlation/time series honestly and label the limitation; do not fake a goniometer.

- [ ] **Step 5: Commit**

```bash
git add runtime/mastering_panel_v17.html runtime/mastering.py runtime/test_mastering_analysis_payload.py
git commit -m "feat: add real mastering analysis views"
```

---

### Task 6: Add Director Plan, verification and rerender workflow surfaces

**Files:**
- Modify: `runtime/mastering_panel_v17.html`
- Modify: `runtime/test_mastering_panel_v17.py`

**Interfaces:**
- Consumes Director plan/verification endpoints from core plan.
- Shows intent, protected traits, per-section reasons, bounds, PASS/REVIEW/REJECTED state and revision chain.

- [ ] **Step 1: Add tests for Director/QA visibility rules**

A processed action without a reason must render as an error state, not disappear.

- [ ] **Step 2: Implement Director Plan inspector**

Top summary: artistic intent and protected traits. Detail: sections/actions with exact reason and bounds.

- [ ] **Step 3: Implement verification surface**

PASS/REVIEW/REJECTED status, failed checks, exact time ranges, source/master deltas, and link back to timeline.

- [ ] **Step 4: Implement revision chain**

Show every render attempt, verification status, and what changed from previous attempt. Never overwrite history.

- [ ] **Step 5: Gate Final/Approved UI action**

Disable approve/export-as-final until server reports verification PASS; the server remains the authority.

- [ ] **Step 6: Commit**

```bash
git add runtime/mastering_panel_v17.html runtime/test_mastering_panel_v17.py
git commit -m "feat: add director and verification workstation workflow"
```

---

### Task 7: Add metadata forensics, clean export and Experience Memory views

**Files:**
- Modify: `runtime/mastering_panel_v17.html`
- Create: `runtime/test_mastering_metadata_ui_contract.py`

**Interfaces:**
- Metadata view consumes audit + clean-export report.
- Memory view consumes contextual similarity records; no client-side auto-application.

- [ ] **Step 1: Add metadata UI contract tests**

Ensure structural metadata is visually separated from removable optional metadata and disclaimer text is present.

- [ ] **Step 2: Implement metadata audit panel**

List detected tags/art/chapter/encoder fields and exactly what clean export removes.

- [ ] **Step 3: Implement Experience Memory evidence panel**

For each similar case show similarity score, reasons, prior decision summary, QA status and Rico feedback. Use an explicit `Use as context` action that sends evidence to Director flow rather than applying DSP.

- [ ] **Step 4: Commit**

```bash
git add runtime/mastering_panel_v17.html runtime/test_mastering_metadata_ui_contract.py
git commit -m "feat: add metadata and mastering memory workstation views"
```

---

### Task 8: Polish live states, accessibility, iOS behavior and failure recovery

**Files:**
- Modify: `runtime/mastering_panel_v17.html`
- Modify: `runtime/test_mastering_panel_v17.py`
- Modify: `runtime/mastering_mcp_server.py` only for missing progress/status APIs

**Interfaces:**
- Workstation operation states: uploading, analyzing, planning, rendering, verifying, approved, failed.

- [ ] **Step 1: Replace generic spinners with stage-specific live state**

Timeline/section status changes as work advances. Use `aria-live` for text status updates.

- [ ] **Step 2: Implement reconnect/reload recovery**

Refreshing the panel reconstructs state from server assets/revisions; active work and completed outputs do not disappear from UI state.

- [ ] **Step 3: Verify iOS-safe interaction**

No hover-only controls, no inaccessible tiny hit targets, no nested scrolling for the main UI, no audio playback assumptions that violate iOS user-gesture requirements.

- [ ] **Step 4: Add explicit error surfaces**

Network/API/audio-decoder errors identify the operation and preserve the user's current asset/revision selection.

- [ ] **Step 5: Commit**

```bash
git add runtime/mastering_panel_v17.html runtime/mastering_mcp_server.py runtime/test_mastering_panel_v17.py
git commit -m "fix: polish mastering workstation live and ios behavior"
```

---

### Task 9: Release acceptance and v17 activation

**Files:**
- Modify: `runtime/mastering_mcp_server.py`
- Modify: `docs/EIROS_CURRENT_HANDOFF.json` if it tracks current mastering panel/engine versions

**Interfaces:**
- Promotes v17 workstation as default MCP resource only after acceptance.

- [ ] **Step 1: Run complete mastering test suite**

```bash
python3 -m pytest runtime/test_mastering_*.py -v
```

Expected: PASS.

- [ ] **Step 2: Compile mastering runtime**

```bash
python3 -m py_compile runtime/mastering*.py
```

Expected: PASS.

- [ ] **Step 3: Manual desktop acceptance**

Use Ayibobo as the bass-dominant case and The Void as a second real-world case. Verify upload, analyze, source playback, Director plan, render, A/B, timeline, QA, metadata audit, revision history, download.

- [ ] **Step 4: Manual ChatGPT iOS acceptance**

Verify panel renders rather than a gray rectangle; controls respond; timeline is readable; audio can start after explicit user gesture; source/master switching works; no horizontal page overflow.

- [ ] **Step 5: Promote `PANEL_URI` to v17**

Keep v16 as legacy fallback for one release cycle.

- [ ] **Step 6: Check service health and journal after restart**

Confirm actual mastering service unit before restart, then inspect bounded journal for startup/runtime errors.

- [ ] **Step 7: Commit release UI**

```bash
git add runtime/mastering_mcp_server.py runtime/mastering_panel_v17.html docs/EIROS_CURRENT_HANDOFF.json
git commit -m "feat: release eIROS mastering workstation v17"
```

