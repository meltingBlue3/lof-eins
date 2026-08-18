# Phase 4: Postprocess Pipeline Hardening - Context

**Gathered:** 2026-08-18
**Status:** Ready for planning

<domain>
## Phase Boundary

`src/data/postprocess.py`'s suspend/resume interval-building logic (the module responsible for the `89830c8` 7x-PnL-inflation bug) gets regression test coverage, a validation gate that can block bad writes, and crash-safe table writes. Requirements: STAB-01, STAB-02, STAB-03. No new capabilities — hardening only.

</domain>

<decisions>
## Implementation Decisions

### validate() blocking behavior
- **D-01:** ANY issue `validate()` detects (open restriction >180 days without resume, `effective_date < announcement_date`) blocks the write — no severity tiers, no count threshold. Rationale: this module already shipped one undetected correctness bug; maximal strictness is preferred over convenience.
- **D-02:** Blocking is the default, always-on behavior — not gated behind a `--strict` flag. — **Reversibility:** reversible — a flag could be added later without breaking anything, but the intent is this is not opt-in.
- **D-03:** When blocked, `scripts/parse_announcements.py` prints the specific list of validation issues, does NOT write to `limit_events`, and exits non-zero. The previous `limit_events` table (from the last successful run) is left untouched and queryable — no separate "pending review" table needed. — **Reversibility:** reversible.

### Atomic table swap
- **D-04:** Write to `limit_events_new`, and only after all inserts succeed, swap it in via `DROP TABLE limit_events; ALTER TABLE limit_events_new RENAME TO limit_events` inside one transaction. On any failure during the write phase, `limit_events_new` is dropped/abandoned and the live `limit_events` table is never touched.
- **D-05:** After a successful swap, the old table's data is discarded — no `limit_events_prev` backup table is kept. Rationale: `limit_events` is fully derivable from `subscription_restrictions` (source of truth), so keeping a rolling backup adds cleanup complexity for no real recovery benefit — re-running postprocess from `subscription_restrictions` IS the recovery path.

### Test coverage
- **D-06:** `tests/test_postprocess.py` covers the full state-machine matrix for `build_limit_events()`, not just the two historical bug scenarios:
  1. Normal suspend→resume pairing (happy path)
  2. Holiday-resume-in-the-middle does NOT close a real suspension (the `89830c8` bug #1)
  3. Missing-prior-suspend synthetic interval — a fund whose first non-holiday event is a resume gets a synthetic `2000-01-01`-start interval (the `89830c8` bug #2)
  4. Unmatched open-ended suspend (no resume found at all) — must produce a NULL-end-date open interval, not be silently dropped
  5. Unknown/new `restriction_type` value — must fail loudly (raise or record as an error), never silently fall through existing branches as if it were a known type
- **D-07:** Tests use a real temporary SQLite database (`tempfile.mkdtemp()`) with hand-constructed `subscription_restrictions` rows, matching the project's existing test convention (see `TESTING.md` — no mocking library used anywhere in this codebase). Also verify `write_limit_events()`'s atomic-swap behavior directly (a forced mid-write failure must leave the previous `limit_events` table intact).

### Existing data handling
- **D-08:** After Phase 4's implementation is complete, run `postprocess()` once against the real `fund_status.db` as a validation step (not automated — a manual check during phase execution/verification). If `validate()` legitimately flags real historical restriction records (e.g., a fund genuinely suspended >180 days), that is a real data-quality finding to triage at that point — not something to pre-emptively soften the validation logic for. If it turns out the hard-block would wrongly halt the pipeline on legitimate data, surface that finding rather than silently loosening D-01's "any issue blocks" rule.

### Claude's Discretion
- Exact schema/return shape of `validate()`'s issue list (as long as it's structured enough for `scripts/parse_announcements.py` to print specific, actionable messages)
- Whether the atomic swap is implemented as a method on the existing `postprocess.py` module or a small helper — no new module/file structure was discussed as necessary
- Naming/structure of new test helper functions in `tests/test_postprocess.py`

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Risk analysis / current state
- `.planning/codebase/CONCERNS.md` — full audit of `postprocess.py`'s fragility, including the exact `_is_holiday_resume()` heuristic risk and the five test scenarios named in D-06
- `.planning/codebase/ARCHITECTURE.md` — Announcement Extraction Layer section; describes `postprocess.py`'s role and the `write_limit_events()` full-table-rewrite anti-pattern
- `.planning/codebase/TESTING.md` — existing test conventions (`unittest`, real temp SQLite, no mocking) that D-07 follows

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` — STAB-01, STAB-02, STAB-03 (this phase's requirements)
- `.planning/ROADMAP.md` — Phase 4 section (goal, success criteria)
- `.planning/PROJECT.md` — "Current State" section describes the `89830c8` bug this phase hardens against

### Source of truth for the bug being guarded against
- `src/data/postprocess.py` — the module being hardened (`_is_holiday_resume()`, `build_limit_events()`, `validate()`, `write_limit_events()`, `postprocess()`)
- Commit `89830c8` — the historical fix this phase adds regression coverage for

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `tests/test_announcement_processor.py:180-330` — existing indirect tests of `postprocess.py` functions (`dedup_records`, `fix_resume_type`) that can inform fixture construction for the new dedicated test file
- Existing SQLite schema in `fund_status.db` (`subscription_restrictions`, `limit_events`) — reuse as-is, no schema changes needed for this phase

### Established Patterns
- `tempfile.mkdtemp()` + real SQLite temp DB is the project-wide test pattern (no mocking) — follow it for `test_postprocess.py`
- Existing rate-limiting pattern in `downloader.py`'s JoinQuant loop (`time.sleep(0.5)`) is NOT relevant to this phase but is referenced elsewhere in the milestone (Phase 6)

### Integration Points
- `scripts/parse_announcements.py` is the CLI entry point that calls `postprocess()` — it needs updating to handle the new non-zero exit / printed-issues behavior from D-03
- `write_limit_events()` is called from `postprocess()`, which is called from `scripts/parse_announcements.py`'s `run()` — the atomic-swap change (D-04) is localized to `write_limit_events()`'s internals; callers shouldn't need signature changes beyond possibly surfacing a raised exception or return status

</code_context>

<specifics>
## Specific Ideas

No UI/visual specifics — this is a backend data-pipeline hardening phase. The core mandate discussed repeatedly: **maximal strictness by default**, because this exact module already shipped a silent correctness bug once (7x PnL inflation, only caught by manual inspection). Every design decision (D-01 any-issue-blocks, D-02 default-on, D-06 full state-machine matrix) leans toward "fail loud" over "fail soft."

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope. (The `--strict` flag idea from `CONCERNS.md`'s original suggestion was explicitly considered and rejected in favor of always-on blocking — see D-02.)

</deferred>

---

*Phase: 4-Postprocess Pipeline Hardening*
*Context gathered: 2026-08-18*
