# EIROS File Vault Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a durable EIROS file vault on the VPS with arbitrary binary storage, metadata/search, temporary public links, browser upload, and a dedicated ChatGPT MCP connector.

**Architecture:** `VaultStore` owns filesystem + SQLite state under `/var/lib/eiros/file-vault`. `file_vault_mcp_server.py` exposes MCP tools and a small Apps-compatible browser panel, while nginx exposes only share/panel HTTP prefixes. Public share tokens are random and only their SHA-256 hashes are persisted.

**Tech Stack:** Python 3.12, stdlib `sqlite3/hashlib/secrets/pathlib`, FastMCP, Starlette, pytest, systemd, nginx, existing EIROS OpenAI tunnel tooling.

**Spec:** `docs/superpowers/specs/2026-08-28-eiros-file-vault-design.md`

## Global Constraints

- Private files do not expire automatically.
- Default share lifetime is 24 hours; valid range is 5 minutes through 30 days.
- External shares require no password and remain reusable until expiry/revocation.
- Default maximum single upload is 2 GiB, configurable by `EIROS_FILE_VAULT_MAX_UPLOAD_BYTES`.
- Maintain a 2 GiB filesystem free-space reserve.
- Storage root is `/var/lib/eiros/file-vault` and is never directly served by nginx.
- SQLite uses WAL mode and foreign keys.
- Raw share tokens are never persisted; only SHA-256 token hashes are stored.
- Browser uploads stream to staging and are atomically moved into object storage.
- VPS imports may resolve only under `/var/lib/eiros` or `/opt/eiros-control-plane`.
- Public shared media must support real HTTP Range requests.
- No S3, MinIO, vector search, remote URL ingestion, or automatic file expiry in V1.

---

### Task 1: Core schema, metadata types, and storage initialization

**Files:**
- Create: `runtime/file_vault/__init__.py`
- Create: `runtime/file_vault/models.py`
- Create: `runtime/file_vault/store.py`
- Create: `tests/test_file_vault_store.py`

**Interfaces:**
- Produces: `VaultConfig`, `VaultFile`, `VaultShare`, `VaultStore(config)`.
- `VaultStore.health() -> dict[str, Any]`
- `VaultStore.get(file_id: str) -> VaultFile`
- `VaultStore.list(query: str = '', tag: str = '', limit: int = 50) -> list[VaultFile]`

- [ ] **Step 1: Write failing initialization/schema tests**

Create tests using `tmp_path` that instantiate `VaultStore(VaultConfig(root=tmp_path / 'vault', max_upload_bytes=1024*1024, reserve_bytes=1024))`, assert directories `objects`, `staging`, `audit` exist, and inspect SQLite `PRAGMA journal_mode` = `wal`, `PRAGMA foreign_keys` = `1`, and presence of `files`/`shares` tables.

- [ ] **Step 2: Run the tests and verify RED**

Run: `PYTHONPATH=. pytest -q tests/test_file_vault_store.py`

Expected: import/module failures because file-vault modules do not exist.

- [ ] **Step 3: Implement minimal models/config/schema**

`VaultConfig` fields:

```python
@dataclass(frozen=True)
class VaultConfig:
    root: Path
    max_upload_bytes: int = 2 * 1024**3
    reserve_bytes: int = 2 * 1024**3
    allowed_import_roots: tuple[Path, ...] = (
        Path('/var/lib/eiros'),
        Path('/opt/eiros-control-plane'),
    )
```

`VaultFile` and `VaultShare` are immutable dataclasses matching the spec fields. `VaultStore.__init__` creates mode-0700 root/object/staging/audit dirs, initializes SQLite, enables WAL and foreign keys, and creates indexes for `created_at`, `display_name`, and `shares.file_id`.

- [ ] **Step 4: Implement `health/get/list`**

`health()` returns root, DB path, total file count/bytes, free bytes, configured max/reserve. `get()` validates a 32-hex file ID and raises `FileNotFoundError` when absent. `list()` performs case-insensitive substring search across display/original name, note and tags JSON; optional normalized tag filter; clamp limit 1..200; newest first.

- [ ] **Step 5: Run focused tests GREEN**

Run: `PYTHONPATH=. pytest -q tests/test_file_vault_store.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add runtime/file_vault tests/test_file_vault_store.py
git commit -m "feat(vault): add durable file vault store"
```

### Task 2: Exact-byte storage, streaming staging, import, verify, and delete

**Files:**
- Modify: `runtime/file_vault/store.py`
- Modify: `runtime/file_vault/models.py`
- Modify: `tests/test_file_vault_store.py`

**Interfaces:**
- Produces:
  - `VaultStore.store_bytes(filename: str, data: bytes, *, source='mcp_upload', tags=(), note='') -> VaultFile`
  - `VaultStore.store_stream(filename: str, chunks: Iterable[bytes], *, source='browser_upload', tags=(), note='') -> VaultFile`
  - `VaultStore.import_path(path: str | Path, *, display_name: str | None = None, tags=(), note='') -> VaultFile`
  - `VaultStore.read_bytes(file_id: str) -> bytes`
  - `VaultStore.object_path(file_id: str) -> Path`
  - `VaultStore.verify(file_id: str) -> dict[str, Any]`
  - `VaultStore.delete(file_id: str) -> dict[str, Any]`

- [ ] **Step 1: Add failing exact-byte and capacity tests**

Tests must assert `store_bytes` preserves `b'\x00\x01abc\xff'` exactly, SHA-256 matches `hashlib.sha256(data).hexdigest()`, size matches, object path contains no original filename, and a payload larger than configured max raises `ValueError` without leaving staging/object files.

Also monkeypatch `shutil.disk_usage` so available space would cross the reserve and assert upload refusal.

- [ ] **Step 2: Add failing streaming cleanup test**

Use a generator that yields two chunks then raises `RuntimeError`; assert `store_stream` propagates and leaves `staging/` empty and no DB row.

- [ ] **Step 3: Implement storage pipeline**

Write chunks to `staging/<uuid>.part`, increment size, update SHA-256 incrementally, enforce max and reserve before finalization, fsync, then `os.replace()` to `objects/<first2>/<file_id>`. Insert metadata only after final object exists. On DB failure, remove finalized object.

MIME comes from `mimetypes.guess_type(filename)[0]` or `application/octet-stream`.

Normalize tags by stripping, lowercasing, deduplicating, sorting, max 32 tags, max 64 chars each. Display/original names are basename-only and max 255 chars.

- [ ] **Step 4: Add/implement safe VPS import**

Resolve source path. It must be a regular file and its resolved path must be equal to or below one configured allowed import root. Copy via `store_stream` in 1 MiB chunks. Source remains unchanged.

Tests: allowed tmp test root via custom config succeeds; a sibling/outside path raises `PermissionError`; symlink escaping an allowed root is rejected.

- [ ] **Step 5: Add/implement integrity and delete behavior**

`verify()` recomputes SHA/size and returns `ok`, expected/actual hash and size. `delete()` removes DB row in a transaction and then object; on missing object it still removes metadata and reports `object_missing=True`. Foreign-key cascade removes shares.

- [ ] **Step 6: Run tests GREEN and commit**

Run: `PYTHONPATH=. pytest -q tests/test_file_vault_store.py`

Commit: `feat(vault): store and verify arbitrary binary files`.

### Task 3: Metadata mutation and temporary share lifecycle

**Files:**
- Modify: `runtime/file_vault/store.py`
- Modify: `runtime/file_vault/models.py`
- Create: `tests/test_file_vault_shares.py`

**Interfaces:**
- Produces:
  - `VaultStore.rename(file_id, display_name) -> VaultFile`
  - `VaultStore.set_tags(file_id, tags) -> VaultFile`
  - `VaultStore.set_note(file_id, note) -> VaultFile`
  - `VaultStore.create_share(file_id, expires_seconds=86400, disposition='inline') -> tuple[VaultShare, str]`
  - `VaultStore.list_shares(file_id) -> list[VaultShare]`
  - `VaultStore.resolve_share_token(raw_token) -> tuple[VaultShare, VaultFile]`
  - `VaultStore.revoke_share(share_id) -> VaultShare`

- [ ] **Step 1: Write failing metadata mutation tests**

Assert rename is metadata-only and original object bytes/hash/path stay unchanged. Assert tags are normalized. Assert notes are capped at 4000 UTF-8 characters.

- [ ] **Step 2: Write failing share lifecycle tests**

Freeze time by monkeypatching `time.time`. Create a 24-hour share and assert:

- raw token length/entropy is high and URL-safe;
- DB contains token hash but not raw token;
- repeated `resolve_share_token(token)` succeeds before expiry;
- unknown token raises `FileNotFoundError`;
- expiry raises `FileNotFoundError`;
- revoke by `share_id` makes token unresolvable;
- private `get/read_bytes` remains valid after expiry/revoke.

Validate expiry range 300..2592000 seconds and disposition enum.

- [ ] **Step 3: Implement mutations/share lifecycle**

Generate raw token with `secrets.token_urlsafe(32)` and persist `sha256(token.encode()).hexdigest()`. Each successful resolve increments `access_count` and updates `last_access_at` in one transaction.

- [ ] **Step 4: Run tests GREEN and commit**

Run: `PYTHONPATH=. pytest -q tests/test_file_vault_shares.py tests/test_file_vault_store.py`

Commit: `feat(vault): add expiring reusable share links`.

### Task 4: Public HTTP share delivery with Range support

**Files:**
- Create: `runtime/file_vault/http.py`
- Create: `tests/test_file_vault_http.py`

**Interfaces:**
- Produces:
  - `share_response(store: VaultStore, token: str, range_header: str | None) -> Response`
  - `not_found_share_response() -> Response`

- [ ] **Step 1: Write failing full-file and Range tests**

Use Starlette `TestClient` around a tiny test route calling `share_response`.

Assertions for a 4096-byte video fixture:

- normal GET: 200, exact body, `Content-Type: video/mp4`, `Accept-Ranges: bytes`;
- `Range: bytes=0-1023`: 206, exactly 1024 bytes, `Content-Range: bytes 0-1023/4096`;
- suffix range `bytes=-100`: last 100 bytes;
- invalid/unsatisfiable range: 416 with `Content-Range: bytes */4096`;
- revoked/expired token: 404, no metadata leakage.

- [ ] **Step 2: Implement bounded single-range parser and streaming response**

Support one RFC 7233 byte range only; reject multiple ranges. Stream file in bounded 1 MiB chunks using a generator that seeks to the selected offset and never reads beyond the selected end.

Headers:

```text
Accept-Ranges: bytes
X-Content-Type-Options: nosniff
Referrer-Policy: no-referrer
Cache-Control: private, no-store
Content-Disposition: inline; filename*=UTF-8''...
```

Use attachment disposition when share says so.

- [ ] **Step 3: Run HTTP tests GREEN and commit**

Run: `PYTHONPATH=. pytest -q tests/test_file_vault_http.py`

Commit: `feat(vault): stream shared files with range support`.

### Task 5: Audit log

**Files:**
- Create: `runtime/file_vault/audit.py`
- Modify: `runtime/file_vault/store.py`
- Modify: `runtime/file_vault/http.py`
- Create: `tests/test_file_vault_audit.py`

**Interfaces:**
- Produces `AuditLogger(path).write(event: str, *, ok: bool, file_id: str | None = None, share_id: str | None = None, size_bytes: int | None = None, detail: str = '')`.

- [ ] **Step 1: Write failing audit privacy tests**

Assert upload/import/rename/tag/note/share-create/share-revoke/delete/share-access write JSON lines containing IDs/timestamps but never raw token or bytes. Assert an `OSError` while writing audit does not roll back an already successful store operation.

- [ ] **Step 2: Implement best-effort JSONL audit**

Open append mode per event with mode 0600. Truncate `detail` to 500 chars. Do not accept or log IP addresses.

- [ ] **Step 3: Run tests and commit**

Run: `PYTHONPATH=. pytest -q tests/test_file_vault_audit.py tests/test_file_vault_store.py tests/test_file_vault_shares.py tests/test_file_vault_http.py`

Commit: `feat(vault): audit file and share lifecycle`.

### Task 6: MCP server and tool contract

**Files:**
- Create: `runtime/file_vault_mcp_server.py`
- Create: `tests/test_file_vault_mcp_server.py`

**Interfaces:**
- Exposes canonical MCP tools:
  - `vault_health`
  - `vault_upload`
  - `vault_import_path`
  - `vault_list`
  - `vault_get`
  - `vault_verify`
  - `vault_download`
  - `vault_rename`
  - `vault_set_tags`
  - `vault_set_note`
  - `vault_share_create`
  - `vault_share_list`
  - `vault_share_revoke`
  - `vault_delete`
  - `open_file_vault`
- Exposes connector-qualified aliases `filevault.<tool>` for compatibility.
- Custom public route: `/s/{token}`.

- [ ] **Step 1: Write failing direct tool tests**

Monkeypatch module-level store to a temp store. Assert upload/download roundtrip exact bytes, annotations are correct for mutating/destructive/open-world tools, share create returns `public_url` under configured external prefix, and tool responses never include internal object paths except `vault_get` may include a deliberately named `internal_path` field.

- [ ] **Step 2: Implement FastMCP server**

Use `TransportSecuritySettings` matching existing EIROS servers. Default local host `127.0.0.1`; port from `EIROS_FILE_VAULT_PORT`, default `8797` and adjust at deployment if occupied.

`vault_upload(filename: str, file_bytes: bytes, tags: list[str] | None = None, note: str = '')` calls `store_bytes`.

`vault_download(file_id) -> bytes` returns original bytes.

`vault_share_create` accepts `expires_hours: float = 24.0`; convert to seconds and return share metadata + external URL.

- [ ] **Step 3: Wire public custom route**

`@mcp.custom_route('/s/{token}', methods=['GET'])` delegates to `share_response`, passing request `Range` header.

- [ ] **Step 4: Run tests GREEN and commit**

Run: `PYTHONPATH=. pytest -q tests/test_file_vault_mcp_server.py`

Commit: `feat(vault): expose dedicated MCP file tools`.

### Task 7: Browser upload/library panel with streaming multipart intake

**Files:**
- Modify: `runtime/file_vault_mcp_server.py`
- Create: `tests/test_file_vault_panel.py`

**Interfaces:**
- Adds MCP resource `ui://eiros/file-vault-v1.html`.
- `open_file_vault()` returns widget resource metadata.
- Adds custom routes under `/ui/api/*`:
  - `POST /ui/api/upload`
  - `GET /ui/api/list`
  - `POST /ui/api/share`
  - `POST /ui/api/share/revoke`
  - `GET /ui/api/download/{file_id}`
  - `POST /ui/api/delete`

- [ ] **Step 1: Write failing multipart streaming test**

Use a 5 MiB fixture and monkeypatch `VaultStore.store_stream` with a wrapper recording chunk sizes. POST multipart file and assert multiple chunks are passed, max observed chunk <= 1 MiB, bytes/hash match, and HTTP response contains metadata.

- [ ] **Step 2: Implement API upload without whole-file read**

Use `request.form(max_files=1, max_fields=8, max_part_size=config.max_upload_bytes)` to obtain `UploadFile`, then an async loop `await upload.read(1024 * 1024)` writing to a staging helper. Because `store_stream` is synchronous, implement `VaultStore.begin_stream_upload()` / `StreamingUpload.write()` / `finish()` / `abort()` or equivalent focused API rather than collecting chunks in memory.

Tests must verify abort cleans staging on HTTP/client error.

- [ ] **Step 3: Implement minimal vanilla panel**

One self-contained HTML resource: file chooser, upload button, search field, recent list, metadata, download, create 24h share, copy/open/revoke, delete with inline two-click confirmation. No external JS/CSS/CDN.

- [ ] **Step 4: Run panel tests and commit**

Run: `PYTHONPATH=. pytest -q tests/test_file_vault_panel.py tests/test_file_vault_mcp_server.py`

Commit: `feat(vault): add browser upload and library panel`.

### Task 8: systemd + nginx deployment artifacts

**Files:**
- Create: `deploy/eiros-file-vault.service`
- Create: `deploy/nginx/eiros-file-vault.conf`
- Create: `docs/FILE_VAULT.md`
- Create: `tests/test_file_vault_deploy_contract.py`

**Interfaces:**
- systemd launches `/opt/eiros-control-plane/venv/bin/python -m runtime.file_vault_mcp_server`.
- nginx public prefix `/vault/s/` proxies to local service `/s/` and preserves `Range`.
- nginx panel/API prefix `/vault/ui/` proxies local `/ui/`.

- [ ] **Step 1: Write failing static deployment contract tests**

Parse files as text and assert:

- service has `Restart=always`, `WorkingDirectory=/opt/eiros-control-plane`, private env root path and explicit port;
- nginx never aliases `/var/lib/eiros/file-vault`;
- nginx forwards `Range` and does not expose `/mcp`;
- docs describe private permanence vs temporary shares and connector fallback behavior.

- [ ] **Step 2: Implement deployment files/docs**

Document default URL, TTL, max size, storage root, backup concern, and examples of every tool.

- [ ] **Step 3: Run static tests and commit**

Run: `PYTHONPATH=. pytest -q tests/test_file_vault_deploy_contract.py`

Commit: `chore(vault): add service and nginx deployment`.

### Task 9: Deploy on VPS and provision dedicated connector

**Files:**
- Deployment state outside git:
  - `/var/lib/eiros/file-vault/`
  - `/etc/systemd/system/eiros-file-vault.service`
  - nginx enabled configuration/snippet
  - OpenAI tunnel/profile/runtime alias `file-vault`

**Interfaces:**
- Local MCP endpoint `http://127.0.0.1:<port>/mcp`.
- Public share prefix `https://ebridge-ui.178-105-43-79.sslip.io/vault/s/`.

- [ ] **Step 1: Fresh repo verification before deployment**

Run all new tests plus baseline:

```bash
PYTHONPATH=. pytest -q tests/test_file_vault_*.py
PYTHONPATH=/opt/eiros-control-plane /opt/eiros-control-plane/venv/bin/pytest -q tests
```

Record exact pass/fail counts.

- [ ] **Step 2: Select unused localhost port and install service**

Check `ss -ltnp`. If 8797 is occupied, use next free 8798..8805 and update service/env/nginx consistently. Create root-only runtime directory and install/reload/start systemd.

- [ ] **Step 3: Install nginx route safely**

Back up active config outside `sites-enabled`, run `nginx -t`, reload only on success. Verify public health/panel prefix does not expose MCP. Verify share route returns 404 for random token.

- [ ] **Step 4: Provision OpenAI connector**

Use existing audited `openai_connector_provision` with alias/name `file-vault`, local MCP URL, and scope inherited from a known-good existing tunnel. Do not print secrets.

Verify daemon health and MCP tool discovery.

- [ ] **Step 5: End-to-end acceptance**

Store a binary fixture, create share, GET twice, Range GET, revoke, ensure 404, internal download still matches. Test browser upload. Test connector list/get/share. Attempt direct ChatGPT binary upload; record whether gateway sends bytes correctly. If not, verify `open_file_vault` browser upload fallback end-to-end.

- [ ] **Step 6: Import current avatar artifacts into Vault**

Import the current LAM first-pass MP4 and current reference/input artifacts that are valid and useful. Tag with `avatar`, `lam`, `2026-08-28`. Do not import known-corrupt/transient staging files.

- [ ] **Step 7: Commit deployment evidence/docs update**

Update `docs/FILE_VAULT.md` with actual port, service status, connector alias and acceptance evidence. Commit `docs(vault): record live acceptance`.

### Task 10: Final verification and integration decision

**Files:**
- Modify only files exposed by verification defects or final evidence docs.

- [ ] **Step 1: Run fresh vault suite**

`PYTHONPATH=. pytest -q tests/test_file_vault_*.py`

- [ ] **Step 2: Run repository baseline**

`PYTHONPATH=/opt/eiros-control-plane /opt/eiros-control-plane/venv/bin/pytest -q tests`

Do not claim unrelated pre-existing deploy SSL collection tests are fixed unless they were intentionally addressed.

- [ ] **Step 3: Verify live service and public Range**

Check systemd active, MCP endpoint response, nginx 404 on bogus token, 200 and 206 on a temporary test share, and byte-identical connector download.

- [ ] **Step 4: Review git status and diff**

Ensure unrelated untracked `runtime/osint-build/`, `runtime/sam.jsonl`, `runtime/sum-controller.jsonl`, or `runtime/widget-blackbox.jsonl` are untouched.

- [ ] **Step 5: Finish branch**

Use `superpowers:finishing-a-development-branch` after all evidence is fresh. The recommended integration is fast-forward merge to `main` only after the user-approved acceptance behavior is verified live.
