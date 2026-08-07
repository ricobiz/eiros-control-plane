# EIROS Rental Agent Remote Browser — Design

Date: 2026-08-08
Status: Approved by Rico for autonomous implementation

## Goal

Replace the one-shot screenshot/click handoff with a sessionful remote-browser surface inside the Rental Agent MCP App. A persistent Chromium context on the VPS is shared by Scout and the in-chat browser UI so cookies and authenticated/verified state survive card refreshes and ordinary agent navigation.

## Authority model

- Agent may autonomously navigate, scroll, follow links, fill ordinary forms, inspect listings, and operate rental-source UI.
- When a page is explicitly detected as human verification/CAPTCHA/Cloudflare challenge, automated challenge-solving is not performed. The remote browser waits for a user-originated gesture from the MCP App and then forwards that gesture to the same VPS Chromium session.
- QR/OTP/login handoffs follow the same rule: authentication proof originates from the user; subsequent normal channel operation is autonomous.

## Architecture

1. `RemoteBrowserController` owns one dedicated daemon thread.
2. That thread exclusively owns Playwright sync objects: persistent Chromium context, pages, and session registry.
3. Commands cross the thread boundary through a bounded queue/future call interface; FastMCP never touches Playwright objects directly.
4. Each remote session has a stable `session_id`, source, page, sequence number, last frame hash, verification state, and timestamps.
5. Browser profile remains `/var/lib/eiros-rental/browser/search` so Scout and remote-browser share cookies/storage.
6. Legacy `rental_browser_snapshot/click` remain temporarily as compatibility wrappers.

## MCP tools

- `rental_browser_open(source)` -> create/reuse session and return initial frame metadata.
- `rental_browser_frame(session_id, after_seq=0)` -> return a JPEG frame only when changed/newer than `after_seq`, plus URL/title/status.
- `rental_browser_input(session_id, event_type, ...)` -> pointer, scroll, key, text, back, reload; `user_gesture=true` is required when verification is active.
- `rental_browser_close(session_id)` -> close page/session without deleting persistent browser profile.
- existing `rental_browser_status()` reports backend/session counts.

## UI

The existing browser panel becomes a remote viewport:
- source tabs for Batdongsan and Nha Tot;
- live image frame with adaptive polling;
- tap and swipe gestures mapped to VPS viewport coordinates;
- Back, Reload, Close controls;
- small text-entry handoff for OTP/search text when needed;
- polling pauses when card is hidden and slows when idle;
- clear status when verification requires a human gesture.

For iOS, the viewport uses Pointer Events with pointer capture and `touch-action:none`; a short gesture becomes a tap, a moved gesture becomes a remote scroll. Desktop click remains a fallback only when no pointer event was handled.

## Performance

- JPEG quality around 50–55 at 1280x900.
- UI polls roughly every 0.9 s while active and 2.5 s while idle; unchanged frames omit base64 payload.
- One Playwright context is reused rather than relaunched per frame/action.
- Commands are serialized by the browser thread to avoid Playwright/event-loop races.

## Failure/recovery

- Browser thread startup failure returns `browser_error` without crashing MCP.
- Unknown/expired session returns `session_not_found` and UI reopens source.
- If page crashes, the controller recreates only that page.
- Service restart loses ephemeral `session_id`s but not cookies/profile; reopening restores the source with prior persistent browser state.

## Testing

- Unit tests for session lifecycle, frame sequence/change suppression, coordinate input, scroll, navigation, verification gate, and close.
- UI contract tests for pointer events, adaptive polling, controls, and MCP tool names.
- MCP catalog tests for the four new tools.
- Live smoke against Batdongsan challenge through the production service; verify frame bytes and persistent session reuse.
