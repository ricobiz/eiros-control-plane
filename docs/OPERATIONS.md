# EIROS operations

## Operator commands

```bash
eiros init --display-name EIROS --channel default --widget-domain https://example.invalid
eiros doctor
eiros status
eiros signal "Remote event text"
eiros test-pulse
eiros release-check
```

## Health states

- `ready` — all critical checks and configured warnings pass.
- `degraded` — core operation is available but a warning requires attention.
- `failed` — at least one critical invariant failed.

The doctor checks instance identity, writable data directories, queue schema, event schema, worker heartbeat, available disk and source integrity.

## Restart recovery

Worker startup performs maintenance before emitting a boot report:

- legacy duplicate startup tasks are cancelled;
- expired task leases are released;
- expired Pulse claims return to pending;
- expired channel leaders are removed;
- a boot report is emitted once per Linux boot ID.

## Backup

Source is stored in GitHub and a complete Git bundle is refreshed locally. Runtime state is deliberately not committed. Production deployments must back up `EIROS_DATA_DIR` separately using encrypted snapshots.

## Upgrade

A production release uses an immutable release directory and a `current` symlink. The data directory stays outside the release. The intended flow is:

1. install dependencies into the managed virtual environment;
2. run the complete release gate;
3. create the new release directory;
4. switch the `current` symlink atomically;
5. restart worker and tunnel;
6. run doctor and a Pulse test;
7. revert the symlink on failure.

## Incident rule

Never delete queue or event files to resolve a fault. Preserve them, inspect the doctor and maintenance reports, and restore from a verified snapshot when corruption is confirmed.
