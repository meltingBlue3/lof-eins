---
status: testing
phase: 04-postprocess-pipeline-hardening
source: [04-VERIFICATION.md]
started: 2026-08-18T00:00:00Z
updated: 2026-08-18T00:00:00Z
---

## Current Test

number: 1
name: Hard process-kill durability of write_limit_events()
expected: |
  Seed `limit_events` with known rows, start a `write_limit_events()` call with a large
  events list, and `kill -9` (or `TerminateProcess`) the Python process partway through
  the insert loop. Reopen the same SQLite file: `limit_events` is byte-identical to its
  pre-write state, and `sqlite_master` contains no `limit_events_new` table.
awaiting: user response

## Tests

### 1. Hard process-kill durability of write_limit_events()
expected: |
  `limit_events` is byte-identical to its pre-write state after an OS-level process kill
  mid-write, and no `limit_events_new` staging table lingers in `sqlite_master`.
  Why this needs a human: this must exercise real OS-level process termination, which
  cannot run inside the same Python test process that would need to survive to make the
  assertion. `04-03-PLAN.md` tags this exact truth `verification: backstop` for that
  reason — the exception-driven rollback path (the practically common failure mode) is
  already thoroughly tested by `TestAtomicSwap` and is not in question here.
result: [pending]

## Summary

total: 1
passed: 0
issues: 0
pending: 1
skipped: 0
blocked: 0

## Gaps
