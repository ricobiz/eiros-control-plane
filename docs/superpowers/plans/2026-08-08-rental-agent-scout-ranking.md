# EIROS Rental Agent Scout + Ranking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Rental Agent foundation into a working autonomous discovery pipeline that can fetch public rental sources, normalize facts, deduplicate listings, rank them against the active Phu Quoc profile, persist search runs, and expose the result through MCP/UI.

**Architecture:** Keep the existing dedicated Rental Agent MCP as a modular monolith. Add pure normalization/ranking modules first, then durable schema v2 and entity resolution, then source adapters and a bounded Scout orchestrator. HTTP discovery is primary; browser escalation is represented explicitly as `needs_browser` and added after the HTTP path is proven.

**Tech Stack:** Python 3.12, SQLite, FastMCP, httpx, stdlib HTMLParser/regex/hashlib, pytest.

## Global Constraints

- Current authority remains `market_discovery_only`.
- No negotiation, viewing scheduling, commitments, deposits, money, or contracts.
- No CAPTCHA bypass or anti-bot circumvention.
- Search/outreach must remain bounded and auditable.
- Current target: Phu Quoc; Sunset Town / Primavera / The Center / nearby New An Thoi; whole building; 3–6 floors; target 18–25m VND/month; stretch max 30m.
- Existing connector/tunnel/UI contract must remain backward compatible.

---

### Task 1: Normalization and explainable fit scoring
**Files:** create `runtime/rental_agent/normalize.py`, `runtime/rental_agent/ranking.py`; test `test_normalize.py`, `test_ranking.py`.
- [ ] Write failing tests for Vietnamese/English price, floor, area, project/zone, whole-building clues and phone extraction.
- [ ] Implement deterministic normalization with explicit confidence/evidence.
- [ ] Write failing tests for budget/location/floors/whole-building scoring and hard rejection.
- [ ] Implement explainable score dimensions and total score.
- [ ] Run focused tests and commit.

### Task 2: Durable schema v2, observations and entity resolution
**Files:** modify `db.py`, `models.py`, `service.py`; create `dedup.py`; tests `test_db_v2.py`, `test_dedup.py`, extend service tests.
- [ ] Add migration v1->v2 without losing existing leads.
- [ ] Persist normalized facts, source fingerprints, contacts, observations and search runs.
- [ ] Implement duplicate matching by exact source, normalized phone, strong listing fingerprint, and high-confidence property signature.
- [ ] Upsert canonical properties and preserve all source records.
- [ ] Run migration/dedup tests and commit.

### Task 3: Public HTTP source adapters
**Files:** create `scout/base.py`, `scout/html.py`, `scout/batdongsan.py`, `scout/nhatot.py`, `scout/web.py`; fixtures/tests under `tests/fixtures` and `test_scout_adapters.py`.
- [ ] Define bounded adapter contract and result/error states.
- [ ] Implement HTML link extraction and listing-detail parser helpers.
- [ ] Implement Batdongsan and Nha Tot search/result adapters using normal HTTP only.
- [ ] Implement generic public-web seed adapter for configured search URLs.
- [ ] Fixture-test parsing and source-change behavior; commit.

### Task 4: Scout orchestrator and MCP surface
**Files:** create `scout/service.py`; modify `service.py`, `server.py`; tests `test_scout_service.py`, extend server contract.
- [ ] Implement one search run with per-source limits, timeout, dedup, normalize, rank, persistence and summary.
- [ ] Expose `rental_search`, `rental_sources`, and `rental_refresh` read/write boundaries.
- [ ] Extend `rental_status` with search-run counts/states.
- [ ] Run MCP contract tests and commit.

### Task 5: Live bounded smoke and UI wiring
**Files:** modify `ui/app.html`; tests `test_ui_scout_contract.py`.
- [ ] Add Scout button/run status and show score explanation/freshness/source count.
- [ ] Run bounded live search against current Phu Quoc profile without messaging anyone.
- [ ] Verify DB, shortlist, source provenance and tunnel readiness.
- [ ] Merge to main, restart Rental MCP, rescan connector, and commit live fixes if needed.

### Task 6: Browser escalation foundation
**Files:** create `browser.py`, `tests/test_browser_contract.py`; dependency change only if needed.
- [ ] Detect whether Playwright/browser runtime is already present.
- [ ] Add persistent isolated search browser profile and `needs_user_action`/`needs_browser` states without bypassing challenges.
- [ ] Add one bounded page-fetch API for JS-heavy listings.
- [ ] Smoke test without authenticated personal messaging sessions and commit.
