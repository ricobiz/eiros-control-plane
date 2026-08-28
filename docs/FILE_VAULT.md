# EIROS File Vault

EIROS File Vault is the permanent private file-exchange layer for EIROS. Files stay in private storage until an explicit delete; they do not expire when a public link expires.

## Storage and integrity

Private objects live under `/var/lib/eiros/file-vault` and are never mapped directly into nginx. Every stored file has a random file ID, original/display name, MIME type, byte size, SHA-256, tags, note, timestamps, and audit events. Upload bytes are preserved exactly. The default single-file limit is 2 GiB and the service reserves 2 GiB of free filesystem space.

The MCP surface supports upload, VPS import, list/search, get, verify, exact-byte download, rename, tags, note, share creation/list/revoke, and permanent delete. Internal access is permanent; only an explicit delete removes a private file.

## Temporary public links

A share creates a passwordless secret URL. Anyone who knows that URL can access the file until the share expires or is revoked. A link is reusable; it is not single-use. The default lifetime is **24 hours**, with a supported range from 5 minutes to 30 days. Expiring or revoking a share does not delete the underlying private object.

Public media delivery supports HTTP **Range** requests so Safari/iPhone and other browsers can seek in video/audio/PDF files. Raw share tokens are returned only at creation time; SQLite stores only their SHA-256 hashes.

## Browser upload fallback

Direct MCP binary upload is available as `vault_upload`, but connector gateways may not always map a chat attachment into a binary argument correctly. `open_file_vault` is the reliable browser upload fallback: it opens a private file picker/library panel and streams multipart uploads to staging in bounded chunks.

The browser panel is intentionally not exposed at a predictable `/vault/ui/` path. Deployment generates a long **secret panel prefix** stored in `/etc/eiros/file-vault.env`; nginx proxies only that prefix to the local `/ui/` routes. The public `/vault/s/<token>` surface exposes only temporary shared files and cannot list, upload, import, rename, or delete private files.

## Runtime

- service: `eiros-file-vault.service`
- local MCP: `http://127.0.0.1:<actual-port>/mcp`
- private root: `/var/lib/eiros/file-vault`
- public share base: `https://ebridge-ui.178-105-43-79.sslip.io/vault/s/`
- private panel base: generated at deployment and intentionally not committed

Before an nginx reload, render `deploy/nginx/eiros-file-vault.conf` with the actual localhost port and secret panel prefix, keep backups outside `sites-enabled`, and run `nginx -t`.

## Backup note

The vault is durable on this VPS but is not itself an off-site backup. Back up `/var/lib/eiros/file-vault` (objects plus SQLite) if the files need protection against VPS loss.
