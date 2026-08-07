# Rental Remote Browser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide a sessionful persistent Chromium viewport inside the Rental Agent MCP App so normal browser work is autonomous and only explicit human-verification requires a user gesture.

**Architecture:** A dedicated `RemoteBrowserController` thread owns Playwright and serializes all page operations. FastMCP exposes open/frame/input/close wrappers and the existing App polls changed frames and forwards pointer/scroll/text events. The persistent browser profile is shared with Scout.

**Tech Stack:** Python 3.12, Playwright sync API, FastMCP, vanilla HTML/JS MCP App, pytest.

## Global Constraints

- Preserve `/var/lib/eiros-rental/browser/search` as the persistent profile.
- Do not automate explicit CAPTCHA/human-verification solving; require `user_gesture=true` while verification is active.
- Keep old snapshot/click tools as compatibility wrappers during this release.
- Do not touch unrelated dirty `main` files.

---

### Task 1: Persistent remote-browser controller

**Files:**
- Create: `runtime/rental_agent/remote_browser.py`
- Test: `runtime/rental_agent/tests/test_remote_browser.py`

**Interfaces:**
- Produces: `RemoteBrowserController.open_source`, `frame`, `input`, `close`, `status`.

- [ ] Write failing lifecycle/frame/input tests using a fake page backend.
- [ ] Run focused tests and verify RED.
- [ ] Implement controller state, session model, changed-frame sequence suppression, input routing, and verification gate.
- [ ] Run focused tests and verify GREEN.
- [ ] Commit.

### Task 2: Rental service and MCP surface

**Files:**
- Modify: `runtime/rental_agent/service.py`
- Modify: `runtime/rental_agent/server.py`
- Modify: `runtime/rental_agent/tests/test_server_contract.py`
- Test: `runtime/rental_agent/tests/test_remote_browser_service.py`

**Interfaces:**
- Produces tools: `rental_browser_open`, `rental_browser_frame`, `rental_browser_input`, `rental_browser_close`.

- [ ] Write failing service/catalog tests.
- [ ] Run focused tests and verify RED.
- [ ] Wire a lazily-created controller using the existing search profile directory.
- [ ] Add four MCP tools and compatibility wrappers.
- [ ] Run focused and full Rental tests.
- [ ] Commit.

### Task 3: iOS-safe live viewport UI

**Files:**
- Modify: `runtime/rental_agent/ui/app.html`
- Modify: `runtime/rental_agent/tests/test_ui_scout_contract.py`

**Interfaces:**
- Consumes the four remote-browser MCP tools.

- [ ] Add failing UI contract assertions for `pointerdown`, `pointerup`, `setPointerCapture`, `touch-action:none`, frame polling, Back/Reload/Close, and text input.
- [ ] Run test and verify RED.
- [ ] Replace one-shot screenshot handling with session open, adaptive frame polling, tap/swipe translation, navigation controls, and text handoff.
- [ ] Run UI and full Rental tests.
- [ ] Commit.

### Task 4: Production deployment and live smoke

**Files:**
- No new production files expected.

**Interfaces:**
- Live MCP on `127.0.0.1:8794/mcp`, tunnel profile `rental-agent`.

- [ ] Merge verified branch to `main` without changing unrelated dirty files.
- [ ] Restart `eiros-rental-mcp.service` and verify tunnel readyz.
- [ ] Verify live MCP catalog contains new tools.
- [ ] Open Batdongsan remote session; fetch two frames from same session and verify browser process/context reuse.
- [ ] Verify verification state requires user gesture and returns a valid JPEG frame.
- [ ] Update durable EBRIDGE project state.
