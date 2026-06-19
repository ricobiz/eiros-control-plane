# EIROS TASK AND CONTINUATION PROTOCOL

## Task lifecycle

`queued -> claimed -> running -> verifying -> completed | blocked | failed | cancelled`

## Required task fields

- `id`
- `title`
- `objective`
- `status`
- `revision`
- `step`
- `max_steps`
- `retry_count`
- `max_retries`
- `created_at`
- `updated_at`
- `last_action`
- `last_result`
- `next_step`
- `continuation_allowed`
- `stop_reason`

## Continuation rule

A new step may execute only when all are true:

1. the active task revision matches the revision read before the action;
2. the task is not completed, cancelled, blocked or failed;
3. `continuation_allowed` is true;
4. `step < max_steps`;
5. `retry_count <= max_retries`;
6. the previous action has a verified result;
7. no explicit stop was issued by Rico.

## Mandatory loop

1. Read `CORE.md` when identity or architecture is relevant.
2. Read `state.json` and the active task.
3. Select one concrete next action.
4. Execute through a declared tool.
5. Verify the result independently where possible.
6. Write the result, revision, journal entry and exact next step.
7. Continue only under the continuation rule.

## Stop conditions

- objective complete;
- Rico explicitly stops or changes direction;
- missing meaning or permission that cannot be inferred safely;
- repeated failure reaches retry limit;
- step or lifetime budget exhausted;
- stale revision or conflicting lease;
- action would cross an undeclared high-impact boundary.

## Audit rule

Every state mutation must leave a human-readable journal entry or a machine log containing timestamp, task id, revision, action, result, and next step or stop reason.
