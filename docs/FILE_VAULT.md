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

## Live acceptance — 2026-08-28 UTC

The first VPS deployment used localhost port **8797**. The service was brought up from the isolated feature worktree for acceptance before integration into `main`.

Verified behavior:

- `eiros-file-vault.service` entered `active/running` state;
- local `/mcp` responded with the expected MCP HTTP negotiation error (`406` without `text/event-stream`), proving the endpoint was live;
- a bogus public share token returned `404`;
- a 4096-byte fixture was stored and shared; two full external downloads had the expected SHA-256;
- `Range: bytes=0-1023` returned `206`, exactly 1024 bytes, and `Content-Range: bytes 0-1023/4096`;
- after share revocation the public URL returned `404`, while private download remained byte-identical;
- a real 3 MiB multipart upload through nginx and the secret browser-panel prefix returned `200`, appeared in search, downloaded with the same SHA-256, and deleted successfully;
- the private panel itself returned `200` through its generated secret prefix;
- an MCP client discovered 30 canonical/compatibility tools and successfully called `vault_list`;
- the managed OpenAI tunnel alias `file-vault` was provisioned and its systemd tunnel daemon reported `active/running` and `ready`;
- the current already-open ChatGPT session did not hot-refresh its connector namespace list after provisioning. This is a session mount limitation; local MCP and the managed remote tunnel were independently verified. Direct ChatGPT attachment-to-binary upload therefore remains to be tested after the new connector is mounted in a refreshed session. The browser upload panel is the supported fallback regardless.

The following existing avatar artifacts were imported into permanent Vault storage with tags and integrity hashes: the first LAM render, its iPhone-safe transcode, the inference log, and the recorded LAM environment. Known-corrupt/placeholder reference files were intentionally not imported.
