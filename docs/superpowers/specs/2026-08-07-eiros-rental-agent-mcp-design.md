# EIROS Rental Agent MCP — Design

Date: 2026-08-07
Owner: Rico
Operator surface: ChatGPT
Execution surface: EIROS VPS through EBRIDGE MCP
Status: Approved architecture, ready for implementation planning

## 1. Objective

Build a fully self-contained rental-search and market-discovery contour on Rico's VPS, controlled entirely from the current ChatGPT conversation through MCP tools. No separate daily-use dashboard is required.

The contour must support two entry modes:

1. Autonomous discovery: search public rental listings and agency inventory on its own.
2. User-supplied leads: ingest a phone number, listing URL, photo, screenshot, or other lead supplied in ChatGPT.

For the current phase, the system performs market discovery only. It finds, normalizes, deduplicates, ranks, and verifies promising properties, then contacts qualified owners/agents to learn current availability, asking price, lease term, deposit/payment schedule when disclosed, exact location/basic property facts, and missing photos/video when useful.

The current phase does not negotiate, book viewings, promise a rental, agree to deposits, send money, or accept/sign contracts.

## 2. Current search profile

Primary geography:
- Phu Quoc, Vietnam
- Sunset Town
- Primavera
- The Center
- nearby New An Thoi

Property target:
- entire shophouse / entire building only
- 3–6 floors acceptable; 5–6 preferred
- unfinished shell is acceptable
- hotel/room-divided layout is acceptable

Budget:
- target: 18–25 million VND/month
- stretch ceiling: 30 million VND/month for a compelling property

Current shortlist criteria:
- current availability
- actual current rent
- lease duration / minimum term
- deposit/payment schedule if disclosed
- location
- photos/video and physical fit
- source/contact provenance
- observed reliability/adequacy of owner or agent based only on listing consistency and communication behavior

## 3. Authority and disclosure policy

### Allowed autonomously in current phase
- search the web and public listing sources
- ingest user-provided leads
- normalize and deduplicate listings
- rank relevance
- resolve public contact details associated with a listing
- automatically contact leads that clear the relevance threshold
- ask discovery questions about availability, price, lease term, deposit, property facts, location, and missing media
- parse replies and update the property record
- produce shortlists and comparison summaries

### Not allowed in current phase
- negotiate price or material terms
- schedule a specific viewing time
- make any binding commitment
- say that Rico definitely takes/will rent a property
- agree to a deposit
- send money
- sign or accept a contract

When Rico later supplies concrete travel dates and availability and explicitly expands scope, scheduling can be enabled within that supplied window. Binding commitments, payments, and contracts remain separately gated unless explicitly authorized.

### Disclosure policy

Do not volunteer personal biography, nationality, business plans, company details, payment methods, move dates, or other unrelated information. Discovery messages stay strictly focused on the property and current market facts.

## 4. Architecture decision

Use a modular monolith behind one MCP surface.

Why:
- simpler deployment and recovery than many microservices
- one durable database and audit trail
- one MCP connector surface for ChatGPT
- isolated internal modules prevent a single giant file
- easy to split into services later if real load requires it

ChatGPT is the reasoning/operator layer. The VPS is the durable execution layer for browsing, storage, queues, authenticated messaging sessions, and logs.

## 5. Internal components

### 5.1 Scout / Search adapters
Discovers candidate listings from configurable sources.

Initial source classes:
- Batdongsan
- Nha Tot / Cho Tot property listings
- agency web pages
- general web search results
- Facebook groups/Marketplace where an authenticated session and platform behavior allow normal access

Search adapters should prefer ordinary HTTP parsing when sufficient and use browser automation only when a site is dynamic or requires a logged-in session.

No CAPTCHA bypass, anti-bot circumvention, credential theft, or other security bypass is permitted. If a site requires human re-authentication or a CAPTCHA, the item/session enters `needs_user_action`.

### 5.2 Ingest
Accepts leads supplied by Rico through MCP:
- URL
- phone number
- plain text
- image/screenshot reference or extracted metadata/text supplied by ChatGPT

Creates a raw lead record and sends it through normalization/dedup.

### 5.3 Normalizer / Geo-Fit
Extracts and standardizes:
- project / development name
- address / locality
- coordinates when resolvable
- monthly rent and currency
- area / footprint / total floor area
- floor count
- room count
- finish/furniture state
- lease term
- deposit
- available date/status
- source publication/update timestamp

Computes a fit score against the active search profile.

### 5.4 Dedup / Entity resolver
Merges likely duplicate listings into one canonical property record while preserving every source.

Signals include:
- same phone/contact
- same normalized address/project/unit clues
- same photos or image fingerprints when available
- same dimensions/floor count/price patterns
- overlapping textual fingerprints

One building may therefore have several source listings and several agents, each with a different asking price.

### 5.5 Property DB
Use SQLite as the durable primary store, with migrations and JSON fields only where flexible metadata is needed.

Core entities:
- properties
- listing_sources
- contacts
- property_contacts
- media
- observations
- outreach_threads
- messages
- search_runs
- jobs
- audit_events

### 5.6 Contact resolver
Extracts and normalizes public contact channels tied to a listing or agency:
- phone
- Zalo identity/phone when exposed by the listing/contact
- WhatsApp
- Telegram
- website/contact form

It must preserve provenance for every contact method.

### 5.7 Fit gate and outreach queue
Scout may collect broadly, but a lead is contacted only if:
- it is not an obvious duplicate already verified recently
- it clears a configurable relevance threshold
- it has a usable contact method
- it has not exceeded contact/retry limits

Routine discovery outreach to qualified leads requires no per-message manual approval.

### 5.8 Channel adapters
Provide one common send/read interface across supported channels.

Initial priority:
1. Zalo Web
2. WhatsApp Web
3. Telegram Web or an explicitly authorized Telegram session/bot where appropriate

Authenticated sessions live on the VPS in isolated persistent browser profiles owned by the rental-agent service account. Initial login/re-authentication remains a user action (QR/OTP/device confirmation as required by the platform).

The system does not bypass platform authentication or anti-abuse controls.

### 5.9 Conversation ledger
Every outbound/inbound message is persisted with:
- property id
- contact id
- channel
- timestamp
- direction
- raw text
- parsed facts
- send/read/error state
- provenance/session id

This makes communication resumable across ChatGPT branches or restarts.

### 5.10 Reply parser
Extracts facts from replies and updates the canonical property record:
- available / unavailable
- price
- lease term
- deposit
- location clarification
- new media links/files
- factual corrections

Conflicting facts are retained as separate observations with source/time rather than silently overwritten.

### 5.11 Ranking / shortlist
Ranking is based on current criteria and evidence freshness, not only listing text.

A property should receive separate dimensions for:
- price fit
- location fit
- building fit
- evidence freshness
- availability confidence
- source consistency
- contact reliability/adequacy

The reliability/adequacy score must be evidence-based and explainable (for example: answers directly, changes price repeatedly, gives contradictory facts, listing appears stale). It must not infer sensitive personal traits.

### 5.12 Authority gate
All actions pass through a policy gate. The current policy permits market-discovery communication only.

Any future tool/action that can negotiate, schedule, commit, pay, or contract must require the corresponding scope flag before execution.

## 6. MCP surface

Initial tool family:

- `rental_status()` — health, queue, sessions, DB summary
- `rental_search(profile_override?, sources?, limit?)` — run autonomous discovery
- `rental_ingest_url(url)`
- `rental_ingest_phone(phone, context?)`
- `rental_ingest_text(text, context?)`
- `rental_property(property_id)` — canonical full property card
- `rental_shortlist(filters?, limit?)`
- `rental_sources(property_id)` — all duplicate/source listings and price history
- `rental_contacts(property_id)`
- `rental_contact_qualified(property_ids? | search_run_id?)` — enqueue qualified leads through the fit gate
- `rental_threads(property_id? | status?)`
- `rental_thread(thread_id)` — full conversation ledger
- `rental_refresh(property_id? | shortlist?)` — re-check freshness/availability
- `rental_channel_status()` — authentication/session state without exposing secrets
- `rental_channel_login(channel)` — create a user-visible login/QR handoff when authentication is needed
- `rental_set_profile(profile_patch)` — change geography/budget/fit rules
- `rental_policy()` — show current authority/disclosure policy

Exact names may be adjusted during implementation to match existing EBRIDGE conventions, but the capability boundaries must remain.

## 7. Search and browsing execution

Use a layered approach:

1. HTTP/search discovery for low-cost broad coverage.
2. Source-specific parsers for stable structured pages.
3. Playwright browser worker for JS-heavy pages, logged-in sources, media extraction, and messaging channels.

Browser profiles are isolated by purpose/channel. Search browsing and personal messaging sessions must not share cookies unless explicitly necessary.

Rate limits, bounded concurrency, backoff, and per-source cooldowns are mandatory.

## 8. Outbound discovery message behavior

Default first-contact message is minimal and property-specific. It asks only for missing discovery facts, avoiding long templated biographies.

The message generator receives:
- known listing facts
- missing facts
- language/channel
- authority policy

It must not invent facts or imply that a rental decision has been made.

Follow-ups are bounded. A contact that does not answer is not spammed indefinitely.

## 9. Durability and recovery

Durable state lives on the VPS, not in a ChatGPT branch.

Required persistence:
- SQLite DB
- browser/session profiles
- structured logs
- job queue state
- search profile and authority policy

Every meaningful job is idempotent or uses a deduplication key so that reconnects/retries do not resend the same message accidentally.

## 10. Security

- session cookies/tokens are never returned through ordinary MCP responses
- secrets are stored outside the repo with restrictive filesystem permissions
- MCP status tools expose only redacted session state
- outbound messages are logged before/after send
- all channel actions are tied to a property/contact/thread
- no automatic financial action exists in this contour
- user-authenticated personal messaging sessions require explicit initial login

## 11. Error handling

Expected states include:
- `ok`
- `stale`
- `needs_user_action`
- `auth_expired`
- `rate_limited`
- `source_changed`
- `contact_unreachable`
- `parse_uncertain`
- `blocked_by_policy`

Errors should preserve the lead/job and enough context for retry rather than dropping it.

## 12. Testing strategy

Unit tests:
- normalization
- price parsing
- lease-term parsing
- fit scoring
- dedup/entity resolution
- authority gate
- reply fact extraction
- idempotency keys

Fixture/integration tests:
- saved HTML listing pages
- source adapter contracts
- SQLite migrations
- search -> normalize -> dedup -> shortlist flow
- qualified lead -> outreach queue flow using a fake channel adapter
- inbound reply -> fact update flow

Browser/channel smoke tests:
- persistent profile launch
- logged-out detection
- QR/login handoff
- send/read against a non-production test conversation where available

No real owner/agent messages are sent during automated tests.

## 13. Delivery sequence

Phase 1: core DB + schema + policy + MCP skeleton
Phase 2: ingest + normalize + dedup + ranking
Phase 3: autonomous Scout/search adapters
Phase 4: persistent browser worker
Phase 5: Zalo adapter and login handoff
Phase 6: WhatsApp/Telegram adapters
Phase 7: reply parser + conversation ledger + automatic qualified outreach
Phase 8: current Phu Quoc search profile end-to-end verification

## 14. Success condition for v1

From ChatGPT, Rico can say in effect: "find current whole shophouses around Sunset Town under my budget" or provide a URL/phone/screenshot lead. EIROS can autonomously discover/ingest candidates, deduplicate them, rank them, contact only qualified leads for market-discovery facts, retain the conversations and facts durably, and return a current shortlist without requiring a separate interface.
