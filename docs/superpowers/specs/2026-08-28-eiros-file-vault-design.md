# EIROS File Vault Design

## Status

Approved by Rico on 2026-08-28. Rico explicitly delegated implementation details and asked not to stop for intermediate approvals.

## Goal

Create one durable, general-purpose file exchange layer on the EIROS VPS so files stop living in ad-hoc mastering, MuseTalk, nginx, or temporary upload locations.

The Vault must support:

- permanent private storage for EIROS;
- arbitrary file types without transcoding or modification;
- upload into the Vault and download out of it;
- persistent file metadata, search and tags;
- temporary external links with no password;
- external links reusable until expiry, not single-use;
- explicit revocation of external links;
- browser-friendly inline delivery and HTTP Range support for video/audio/PDF;
- direct use by ChatGPT through a dedicated MCP connector;
- a minimal browser upload panel as a reliable fallback for device uploads when connector binary transport is unavailable;
- safe import of files that already exist on the VPS.

Internal Vault files do **not** expire automatically. Expiry applies only to external share links.

## Non-goals for V1

- S3/MinIO/object-cluster deployment;
- public anonymous browsing or directory listing;
- user accounts or passwords for share links;
- virus scanning or content moderation pipeline;
- automatic deletion based on age;
- version history for edited files;
- remote URL ingestion;
- synchronization to third-party cloud drives.

## Architecture

V1 is a single dedicated Python service using the existing EIROS runtime stack:

- FastMCP / Starlette for MCP tools, browser upload API and public share delivery;
- SQLite for metadata and share state;
- normal filesystem storage under `/var/lib/eiros/file-vault`;
- nginx exposes the public share path and a separate unguessable private upload-panel prefix;
- the MCP endpoint stays local and is exposed to ChatGPT through the existing OpenAI tunnel mechanism.

No MinIO is added. The storage backend is deliberately hidden behind a small `VaultStore` interface so a later S3 backend can replace the filesystem without changing MCP tool semantics.

## Storage layout

Root: `/var/lib/eiros/file-vault`

```text
/var/lib/eiros/file-vault/
  vault.sqlite3
  objects/
    ab/
      <file_id>
  staging/
  audit/
    events.jsonl
```

Each file gets a random 32-hex-character `file_id`. The stored object filename is the `file_id`, not the original filename. Original/display names exist only in SQLite metadata.

V1 intentionally does not deduplicate content. A SHA-256 is still stored for integrity verification.

## File metadata

`files` table fields:

- `file_id` TEXT PRIMARY KEY;
- `original_name` TEXT NOT NULL;
- `display_name` TEXT NOT NULL;
- `media_type` TEXT NOT NULL;
- `size_bytes` INTEGER NOT NULL;
- `sha256` TEXT NOT NULL;
- `object_relpath` TEXT NOT NULL;
- `source` TEXT NOT NULL (`mcp_upload`, `browser_upload`, `vps_import`);
- `tags_json` TEXT NOT NULL;
- `note` TEXT NOT NULL DEFAULT '';
- `created_at` INTEGER NOT NULL;
- `updated_at` INTEGER NOT NULL.

A stored object is valid only when its resolved path remains under the configured object root and its size matches metadata. Integrity verification can additionally recompute SHA-256 on demand.

## Share metadata

`shares` table fields:

- `share_id` TEXT PRIMARY KEY;
- `file_id` TEXT NOT NULL REFERENCES files(file_id) ON DELETE CASCADE;
- `token_hash` TEXT UNIQUE NOT NULL;
- `created_at` INTEGER NOT NULL;
- `expires_at` INTEGER NOT NULL;
- `revoked_at` INTEGER NULL;
- `access_count` INTEGER NOT NULL DEFAULT 0;
- `last_access_at` INTEGER NULL;
- `disposition` TEXT NOT NULL (`inline` or `attachment`).

The raw share token is generated with at least 256 bits of entropy and returned only at creation time. SQLite stores only SHA-256 of the token. A listed share therefore exposes `share_id`, timestamps and status but not a reusable token. If a URL is lost, create another share.

Default external link lifetime: 24 hours. Caller may request from 5 minutes to 30 days. Links are reusable until expiration. A share can be revoked immediately by `share_id`.

## Public URLs

Public link form:

```text
https://ebridge-ui.178-105-43-79.sslip.io/vault/s/<opaque-token>
```

No file ID, internal path or original filename is embedded in the URL.

The share endpoint:

- resolves the token by its hash;
- rejects unknown, revoked or expired shares with 404;
- increments access counters without storing requester IP;
- serves the original bytes;
- sets the persisted media type;
- uses `Content-Disposition: inline` for inline shares and `attachment` otherwise;
- sends `Accept-Ranges: bytes` and must pass a real `Range: bytes=...` acceptance test;
- sends `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and conservative cache headers.

The public share location exposes only `/vault/s/`. Private upload/library routes are reachable only through a separately generated long secret panel prefix stored outside git. Nginx never exposes `/var/lib/eiros/file-vault` directly and never exposes the Vault `/mcp` endpoint.

## Upload paths

### MCP binary upload

`vault_upload(filename, file_bytes, tags=[], note='')`

The MCP connector exposes a binary/file parameter. The service stores exactly the bytes received and returns metadata including SHA-256. This path is tested against the ChatGPT connector after provisioning.

### Browser upload panel

`open_file_vault()` renders a small MCP Apps-compatible upload/library panel. The browser posts multipart data to `/vault/ui/api/upload` in chunks handled by Starlette `UploadFile`; the implementation writes to a staging file incrementally and does not load the entire upload into RAM.

This is the reliable fallback for uploads directly from iPhone/filesystem if connector file transport cannot map a chat attachment to the MCP binary parameter.

### VPS import

`vault_import_path(path, display_name=None, tags=[], note='')`

Allowed source roots in V1:

- `/var/lib/eiros`;
- `/opt/eiros-control-plane`.

The imported file is copied into Vault storage; the source is not moved or deleted. Symlinks are resolved and must remain under an allowed root.

## Capacity and safety limits

- Default max single upload: 2 GiB, configurable by `EIROS_FILE_VAULT_MAX_UPLOAD_BYTES`.
- Maintain a 2 GiB filesystem free-space reserve. Upload/import is refused if accepting the file would cross that reserve.
- Browser uploads stream into `staging/`; failed uploads remove the staging file.
- Final object placement uses atomic rename within the same filesystem.
- Database uses WAL mode and foreign keys.
- Original filenames are sanitized for HTTP headers only; storage paths never use user-controlled filenames.
- No endpoint accepts arbitrary destination filesystem paths.

## MCP tool surface

### Read tools

- `vault_health()` — service, DB and storage capacity status.
- `vault_list(query='', tag='', limit=50)` — newest-first metadata search.
- `vault_get(file_id)` — metadata and active share summaries.
- `vault_verify(file_id)` — recompute size/SHA-256.
- `vault_download(file_id) -> bytes` — return the original bytes to ChatGPT.
- `vault_share_list(file_id)` — share IDs and expiry/revocation state.
- `open_file_vault()` — open browser upload/library panel.

### Mutating tools

- `vault_upload(filename, file_bytes, tags=[], note='')` — store binary content.
- `vault_import_path(path, display_name=None, tags=[], note='')` — copy an existing VPS file into Vault.
- `vault_rename(file_id, display_name)` — metadata-only rename.
- `vault_set_tags(file_id, tags)` — replace normalized tags.
- `vault_set_note(file_id, note)` — replace note.
- `vault_share_create(file_id, expires_hours=24, disposition='inline')` — create temporary public URL.
- `vault_share_revoke(share_id)` — revoke one URL.
- `vault_delete(file_id)` — permanently delete object, metadata and shares.

Destructive annotations are set correctly for delete/revoke operations. Share creation is `openWorldHint=True`; internal storage operations are `openWorldHint=False`.

## Search behavior

V1 search is deliberately simple and deterministic:

- case-insensitive substring match across display name, original name, note and tags;
- optional exact normalized tag filter;
- newest-first ordering;
- hard maximum 200 results per call.

No embeddings/vector search are required for a file vault.

## Browser panel

The V1 panel is utilitarian, not a full cloud-drive UI. It supports:

- choose/upload arbitrary file;
- upload progress/status;
- list recent files;
- search by name/tag;
- show size, MIME, SHA prefix and created time;
- create a 24-hour share link;
- copy/open the share link;
- download the stored original;
- revoke an active share;
- delete with a two-step confirmation.

The panel uses the existing EBRIDGE UI origin and no third-party resources.

## Audit

Mutations and share accesses append bounded JSON records to `audit/events.jsonl` with:

- timestamp;
- event type;
- file/share IDs when applicable;
- size where applicable;
- success/failure;
- no file contents;
- no raw share token;
- no requester IP.

Audit failure must not corrupt a successful file operation; it is best-effort after state commit.

## Deployment

- Python module: `runtime/file_vault/` plus `runtime/file_vault_mcp_server.py`.
- Local MCP HTTP port: choose an unused localhost port during deployment (expected 8797+).
- systemd service: `eiros-file-vault.service`.
- nginx: `/vault/s/` for public shares plus one generated secret panel prefix; never `/mcp`.
- OpenAI connector/tunnel: provision dedicated alias `file-vault` using the existing audited tunnel tooling.
- Runtime data ownership: root-owned, directory mode 0700; nginx never reads object files directly.

## Acceptance criteria

1. Upload a binary fixture through core store code; downloaded bytes are byte-identical and SHA-256 matches.
2. Import an existing VPS fixture from an allowed root; import outside allowed roots is rejected.
3. Search and tag filtering return deterministic results.
4. Create a 24-hour share, open it repeatedly, and receive the same file each time.
5. `Range: bytes=0-1023` returns HTTP 206 and exactly 1024 bytes for a shared video fixture.
6. Expired/revoked share returns 404 while the private file remains downloadable internally.
7. Deleting a file removes its object and all share rows.
8. Browser multipart upload of a fixture succeeds without loading the full request into one bytes object.
9. MCP `vault_download` returns the exact original file.
10. ChatGPT connector can call list/get/share operations after tunnel provisioning.
11. If ChatGPT direct binary upload is supported by the connector gateway, an attached file can be stored directly; otherwise the browser panel is the supported fallback and this limitation is documented explicitly.
12. Existing EIROS test suite remains green except for already-known unrelated collection failures, which must be reported rather than hidden.
