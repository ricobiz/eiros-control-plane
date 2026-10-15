# EIROS: Out-of-band VPS recovery (2026-10-16)

## Key facts
- Hetzner Cloud instance `ebridge`, IPv4 `178.105.43.79`.
- Primary ChatGPT MCP integrations: `Ebridge VPS Ops` and `EBRIDGE`; **not independent** if shared tunnel/control-plane fails.
- Independent fallback is `GitHub MCP → private ricobiz/eiros-control-plane GitHub Actions → Hetzner Cloud API`.
- Public VPS health: `https://vault.178-105-43-79.sslip.io/v2/health`; valid response `{"ok":true,"isolated":true}`.
- Incident 2026-10-16: both MCP integrations failed despite independently verified public VAULT API being healthy. **Root cause unknown until journals are inspected.** Rebooting VPS blindly is not justified.
- Previous unrelated SSH problem involved an IPv6-only `ssh.socket` override; do not assume recurrence.

## ChatGPT GitHub MCP procedure — works from any conversation
No VPS access is required to create a GitHub issue.

**Read-only provider diagnostic:**
Use `mcp__GitHub__create_issue` with:
`{repository_full_name:"ricobiz/eiros-control-plane", title:"[EIROS-OOB] status", body:"Read-only diagnostic. No reboot."}`

Wait for a `github-actions[bot]` issue comment, then inspect via `mcp__GitHub__fetch_issue_comments({repo_full_name:"ricobiz/eiros-control-plane",issue_number:N})`.

**Explicitly user-approved graceful ACPI reboot ONLY:**
Create GitHub issue with exact title `[EIROS-OOB] graceful_reboot` and exact body
`CONFIRM_GRACEFUL_REBOOT_ebridge_178.105.43.79`.

If VAULT public health is responding, this operation deliberately **fails closed**. An additional line `OVERRIDE_HEALTHY=true` overrides this guard ONLY when the user separately approves rebooting the entire healthy VPS, including unrelated projects.

**Hard reset** (power cut) is NEVER available through issue bridge. It requires GitHub Actions manual workflow `EIROS Hetzner Out-of-Band Recovery`, operation `hard_reset`, exact confirmation `CONFIRM_HARD_RESET_ebridge_178.105.43.79` and second approval `IRREVERSIBLE_POWER_CYCLE`; reserve for genuine host failures and failed graceful recovery.

## One-time setup by owner
The GitHub Actions secret **HCLOUD_TOKEN** is not configured as of the first test on 2026-10-16. The independent GitHub issue #7 produced the confirmed error `GitHub Actions secret HCLOUD_TOKEN is missing`; this proves issue → hosted Actions → result comment works, but Hetzner API access is **not yet operational**.

Owner:
1. Open [Hetzner Cloud Console](https://console.hetzner.com/), choose the correct project with server `ebridge`.
2. Security → API Tokens → generate dedicated **Read & Write** token (read-only is insufficient for ACPI reboot), protect it as a sensitive project-wide credential.
3. In private [eiros-control-plane](https://github.com/ricobiz/eiros-control-plane/settings/secrets/actions), add repository Actions secret named exactly `HCLOUD_TOKEN`. **Never paste the token into ChatGPT, source files or a GitHub issue**.
4. Ask ChatGPT to open a new `[EIROS-OOB] status` issue and inspect its bot comment. Only a successful read-only Hetzner status verifies setup.
5. Keep GitHub Actions enabled and ensure owner `ricobiz` may create issues. No unattended reboot is configured.

## Implementation and safeguards
- `ops/hetzner_oob.py`: independent Python stdlib Hetzner API client; selects VM only when BOTH hostname and IP match; prints safe state; guards against unnecessary reboot; polls provider action.
- `ops/hetzner_issue_bridge.py`: confirms private repo, owner identity and exact issue title/body; permits read-only status and explicitly confirmed **graceful reboot** only; posts sanitized results to issue.
- `.github/workflows/hetzner-oob-issue.yml`: GitHub issue trigger on GitHub-hosted runner; does not depend on VPS, SSH, EIROS tunneling or ChatGPT session.
- `.github/workflows/hetzner-oob-recovery.yml`: manual Actions status/graceful reboot/hard reset with stricter hard reset gate.
- GitHub Actions job concurrency serializes recovery operations. Neither workflow contains an automatic schedule.
- Provider success means hypervisor action succeeded, **not** that MCP/API or all application processes recovered.
- This is an MCP-accessible **GitHub bridge**, not yet a native registered `Hetzner MCP` plugin; do not misrepresent it.

## Root-cause investigation after primary connector/SSH access returns
Gather sanitized read-only evidence BEFORE restarting local services:

```bash
date -Is; uptime -s
systemctl --failed --no-pager
systemctl show eiros-vps-ops.service eiros-tunnel.service eiros-worker.service eiros-root-broker.service -p Id -p ActiveState -p SubState -p NRestarts --no-pager
journalctl -u eiros-vps-ops.service -u eiros-tunnel.service -u eiros-worker.service -u eiros-root-broker.service --since '2026-10-15 15:00 UTC' -n 300 --no-pager
journalctl -k --since '2026-10-15 15:00 UTC' --no-pager | grep -iE 'oom|out.of.memory|killed.process|segfault|i/o error' | tail -60
free -h; df -h / /mnt/HC_Volume_106836491
systemctl status ssh.socket ssh.service --no-pager
```

Do not leak API keys, cookies, bearer credentials or tunnel secrets via journals. Identify cause via timestamps and provider events, then implement local scoped `Restart=on-failure`/watchdog and independent monitoring; **do not auto-reset a healthy multi-project VPS**.

## Retry budget
If both MCP health tools fail once, check independent HTTPS and GitHub OOB status; do not repeatedly call unavailable VPS tools for 20+ minutes.

**Outstanding:** Hetzner token setup, verified provider status, original journal root cause and any local systemd watchdog deployment.
