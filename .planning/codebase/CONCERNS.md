# Codebase Concerns

**Analysis Date:** 2026-08-18

> Scope note: the announcement pipeline was rewritten in April 2026 (commits `4cc5212`, `89830c8`), replacing a sync Ollama LLM client with an async Kimi K2.5 client, adding `src/data/postprocess.py`, and switching NAV downloads to akshare. Commit `89830c8` fixed two silent correctness bugs discovered only after the fact (holiday-resume pairing, missing pre-2022 suspensions) that inflated backtest PnL from ~1M to ~7M CNY. This document treats that rewrite as current state and specifically audits it for similar latent bugs.

## Tech Debt

**`src/data/postprocess.py` has zero dedicated unit tests despite being the most bug-prone module in the codebase:**
- Issue: `dedup_records`, `fix_resume_type`, and `build_limit_events` are exercised only indirectly via `tests/test_announcement_processor.py` (which imports them from `src.data.postprocess`). There is no `tests/test_postprocess.py`. The fix commit `89830c8` — which corrected two bugs that silently tripled reported PnL — added **no new test cases** for `_is_holiday_resume()` or the synthetic-suspend-interval logic in `build_limit_events()` (`src/data/postprocess.py:107-170`).
- Files: `src/data/postprocess.py`, `tests/test_announcement_processor.py:180-330`
- Impact: The exact class of bug that caused the PnL inflation (holiday resumes vs. real resumes, missing pre-data-range suspensions) can regress silently on the next refactor with no test to catch it.
- Fix approach: Add `tests/test_postprocess.py` with explicit cases: (a) a holiday resume between two long-term suspend events must NOT close the interval, (b) a fund whose first non-holiday event is a resume must produce a synthetic `2000-01-01` interval, (c) `restriction_type in ("application_invalid",)` must never pair with a distant resume even when not literally holiday-labeled.

**`_is_holiday_resume()` heuristic is string/substring-based and fragile:**
- Issue: Holiday-vs-real-resume classification relies on `rtype in ("holiday_suspension", "application_invalid")` OR substring checks for `"节假日"` / `"境外"` in `source_file` (`src/data/postprocess.py:107-120`). This is the exact category of heuristic that caused the original bug (a Christmas holiday announcement wasn't recognized and incorrectly closed a real suspension). The substring check is a symptom-level patch, not a structural fix — any announcement whose `source_file` name doesn't contain these exact Chinese substrings (e.g. differently phrased holiday titles, English filenames, or renamed files) will misclassify.
- Files: `src/data/postprocess.py:107-120`
- Impact: New/renamed source filenames could reintroduce phantom-trade-causing bugs identical to the one fixed in `89830c8`, and there's no data-level signal (e.g. explicit `is_holiday` column, or a structured field from the LLM extraction) backing the classification — it's inferred after the fact from text.
- Fix approach: Have the Kimi extraction prompt (`prompts/system_prompt.md`) emit an explicit boolean/enum field for holiday-vs-full resume at extraction time rather than reconstructing it from filename substrings during postprocessing; keep the substring check only as a defensive fallback.

**`validate()` in postprocess.py never fails the pipeline or blocks writes:**
- Issue: `validate()` (`src/data/postprocess.py:309-354`) detects open restrictions >180 days without a resume and `effective_date < announcement_date` anomalies, but only `print()`s them. `postprocess()` (`src/data/postprocess.py:357-389`) calls `validate(records)` then unconditionally proceeds to `build_limit_events()` and `write_limit_events()` regardless of validation findings.
- Files: `src/data/postprocess.py:380-383`
- Impact: Data-quality issues that look exactly like the two bugs fixed in `89830c8` can be flagged by `validate()` and still get written to `limit_events`, silently corrupting backtest results, because nothing consumes the validation output except console text (easy to miss when run non-interactively, e.g. in `scripts/parse_announcements.py`).
- Fix approach: Return validation issues from `postprocess()` in the stats dict, and add a `--strict` flag to `scripts/parse_announcements.py` that aborts the DB write if issues exceed a threshold.

**`write_limit_events()` does a blind `DROP TABLE` + full rewrite with no backup/transaction safety:**
- Issue: `write_limit_events()` (`src/data/postprocess.py:257-306`) drops and recreates `limit_events` on every run, with all inserts inside one implicit transaction but no pre-drop backup and no atomic swap (e.g. write to a temp table then rename).
- Files: `src/data/postprocess.py:262-263`
- Impact: If `build_limit_events()` produces a bad or short result set (e.g. due to a partially-loaded `subscription_restrictions` table, or a bug like the ones fixed in `89830c8`), the previous — possibly correct — `limit_events` table is destroyed before the new (bad) data is validated by a human. There is no rollback path.
- Fix approach: Write to `limit_events_new`, validate row counts against the previous table, then rename tables inside a transaction; keep the last-known-good table as `limit_events_prev`.

**Async concurrency in `AnnouncementProcessor` has no per-request retry/backoff:**
- Issue: `_process_one()` (`src/data/announcement_processor.py:131-148`) catches any exception from `LLMClient.extract_from_pdf` and marks the file as permanently "failed" for that run — no retry, no exponential backoff for transient Kimi API errors (rate limits, timeouts). Retrying requires a separate manual invocation with `--retry-failed`.
- Files: `src/data/announcement_processor.py:131-148`, `src/data/llm_client.py:93-154`
- Impact: With default concurrency of 50 (`DEFAULT_CONCURRENCY = 50`, `src/data/announcement_processor.py:32`), transient rate-limit errors from Moonshot's API under concurrent load will silently reduce yield without automatic recovery, requiring the operator to notice a low success count and manually re-run with `--retry-failed`.
- Fix approach: Add bounded retry (e.g. 2 attempts with jittered backoff) inside `extract_from_pdf` for `httpx`/`openai` transient errors (429, 5xx, timeouts) before surfacing to `_process_one`.

**akshare NAV fetch loop has no rate limiting, unlike the JoinQuant and announcement downloaders:**
- Issue: `_get_nav_data()` (`src/data/downloader.py:169-203`) loops per-ticker calling `ak.fund_open_fund_info_em(...)` with no `time.sleep()` between calls, while the JoinQuant batch loop (`src/data/downloader.py:467`, `time.sleep(0.5)`) and the announcement PDF downloader (`src/data/announcement_downloader.py:178,220,268`) both rate-limit/retry deliberately. The commit message for `4cc5212` notes the switch to akshare was specifically because "JoinQuant finance API has row limits," but no equivalent akshare-specific throttling was added.
- Files: `src/data/downloader.py:169-203`
- Impact: For large batches (`batch_size=50` funds per call, looped per-ticker inside `_get_nav_data`), rapid sequential requests risk akshare/Eastmoney rate limiting or IP blocks, silently degrading to `[WARN] NAV for {ticker}: {e}` per-fund failures that are easy to miss in bulk downloads.
- Fix approach: Add a small delay (e.g. `time.sleep(0.2-0.5)`) inside the per-code loop in `_get_nav_data`, and count/report failed-vs-succeeded NAV fetches at the end of `download()`.

**Two overlapping downloader classes with a naming collision for "download all LOF":**
- Issue: `src/data/downloader.py` exposes `download_all_lof()` and `RealDataDownloader`; `src/data/announcement_downloader.py` exposes `AnnouncementDownloader.download_all_lof_announcements()`. `scripts/download_lof.py` and `scripts/download_announcements.py` are separate entry points. There's no shared base class or consistent naming convention (`download_all_lof` vs. `download_all_lof_announcements` vs. `RealDataDownloader.download`), making it easy to call the wrong script/method when extending the pipeline.
- Files: `src/data/downloader.py`, `src/data/announcement_downloader.py`, `scripts/download_lof.py`, `scripts/download_announcements.py`
- Impact: Low risk of direct bugs, but raises onboarding friction and risk of divergent conventions (e.g. rate limiting present in one downloader, absent in the other — see akshare concern above).
- Fix approach: Not urgent; consider a shared `BaseDownloader` with rate-limiting and retry as common utilities if a third downloader is added.

## Known Bugs

**Fixed but structurally recurring: phantom-trade-causing interval bugs (commit `89830c8`).**
- Symptoms: Backtest PnL was inflated ~7x (from ~1M to ~7M CNY) because `limit_events` intervals were shorter than reality — the engine believed funds were purchasable when they were actually still suspended.
- Files: `src/data/postprocess.py` (`_is_holiday_resume`, `build_limit_events`)
- Trigger: (1) A holiday-resume announcement (e.g. Christmas resumption notice) was treated as terminating a long-term suspension it did not actually lift. (2) Funds suspended before the data collection window (pre-2022-01) had no suspend record at all in `subscription_restrictions`, so the first record seen was a "resume" with no matching prior suspend, leaving the fund appearing tradeable the whole time before that date.
- Workaround: Fixed via `_is_holiday_resume()` filtering and synthetic `2000-01-01`-start intervals (see Tech Debt section above for why this fix is still fragile and untested).

**No current known-open bugs identified in the rewritten pipeline** beyond the fragility noted above; however, because there are no new tests covering the fix, regressions of the same shape cannot be automatically detected — treat this as an open risk rather than a resolved one.

## Security Considerations

**Kimi/Moonshot API key handling relies entirely on environment variables with no rotation or scoping guidance:**
- Risk: `LLMClient.__init__` reads `KIMI_API_KEY` from env or constructor arg (`src/data/llm_client.py:51-56`); `scripts/parse_announcements.py` loads `.env` via `python-dotenv` if present. No `.env.example` audit was performed here beyond confirming the pattern; the key grants file-upload and chat-completion access to the Moonshot account.
- Files: `src/data/llm_client.py:51-56`, `scripts/parse_announcements.py`
- Current mitigation: Standard `.env` + environment variable pattern, key not hardcoded in source.
- Recommendations: Ensure `.env` is git-ignored (verify at repo root) and that uploaded fund-announcement PDFs (not sensitive) plus API key are not committed via `parse_progress.json`, which stores raw extraction `results` on disk (`src/data/announcement_processor.py:58-66`) — confirm this progress file (under `data/real_all_lof/config/parse_progress.json` typically) is also git-ignored, since it could accumulate extracted structured data across runs.

**Uploaded PDFs to Kimi are only best-effort deleted:**
- Risk: `delete_file()` (`src/data/llm_client.py:76-81`) swallows all exceptions silently (`except Exception: pass`), so failed cleanups after `extract_from_pdf` leave files on Moonshot's servers indefinitely with no retry or audit log of orphaned file IDs.
- Files: `src/data/llm_client.py:76-81`
- Current mitigation: `finally` block always attempts deletion.
- Recommendations: Log (not print) failed deletions with the `file_id` so orphaned uploads can be cleaned up in bulk periodically; fund announcement PDFs are public disclosures so the data-sensitivity risk is low, but storage costs/quota exhaustion on the Moonshot account is a real risk at scale (thousands of PDFs processed per run per `DEFAULT_CONCURRENCY = 50`).

## Performance Bottlenecks

**Per-fund sequential akshare NAV calls with no batching:**
- Problem: `_get_nav_data()` issues one `ak.fund_open_fund_info_em()` HTTP call per fund code sequentially inside a Python `for` loop (`src/data/downloader.py:185-199`), for every batch of up to `batch_size=50` funds, across potentially the full universe of LOF funds.
- Files: `src/data/downloader.py:169-203`
- Cause: akshare's `fund_open_fund_info_em` is a per-fund endpoint with no bulk-fetch equivalent used here; combined with no concurrency (unlike the async Kimi pipeline) or caching, a full-universe download is effectively O(n) blocking HTTP calls.
- Improvement path: Consider wrapping the per-code loop in a thread pool (akshare calls are sync/blocking) with modest concurrency (e.g. 5-10 workers) plus the missing rate-limit delay noted in Tech Debt, to balance speed against throttling risk.

**`postprocess()` reloads and reprocesses all historical records on every run (no incremental mode):**
- Problem: `postprocess()` always calls `load_records()` for the entire `subscription_restrictions` table (`src/data/postprocess.py:370`), dedups/fixes/validates everything, and does a full `DROP TABLE`/rewrite of `limit_events` (`src/data/postprocess.py:377-383`), even when only a handful of new announcements were parsed since the last run.
- Files: `src/data/postprocess.py:357-389`
- Cause: No incremental/delta processing path; O(all announcements) work on every invocation.
- Improvement path: Not a near-term concern at current data volumes (hundreds of funds, thousands of announcements), but will become one if the announcement corpus grows by orders of magnitude — consider incremental dedup keyed on new `announcement_date` ranges.

## Fragile Areas

**`build_limit_events()` state-machine pairing logic (suspend → resume interval construction):**
- Files: `src/data/postprocess.py:123-254`
- Why fragile: This is a hand-rolled forward-scan state machine per fund (`while i < len(fund_records)` with an inner `for j in range(i+1, ...)` lookahead to find the matching resume) that encodes multiple special cases inline: holiday vs. non-holiday resumes, single-day-only restriction types (`holiday_suspension`, `application_invalid`), synthetic pre-data-range intervals, and default-to-suspended fallback when `max_amount` can't be determined. The bug fixed in `89830c8` was exactly this kind of edge case falling through the cracks. Any new `restriction_type` or `action` value introduced by future LLM prompt changes (`prompts/system_prompt.md`) that isn't explicitly handled in this function's conditionals will silently fall through the existing branches rather than erroring.
- Safe modification: Any change to this function should be paired with new unit tests covering (a) normal suspend→resume pairing, (b) holiday-resume-in-the-middle, (c) missing-prior-suspend synthetic interval, (d) unmatched open-ended suspend (no resume found), (e) unknown/new `restriction_type` values to confirm they fail loud rather than silently defaulting.
- Test coverage: None dedicated (see Tech Debt above); only indirectly exercised via `tests/test_announcement_processor.py`.

**`fix_resume_type()` inherits `restriction_type` from "the nearest preceding suspend/restrict" per fund, in effective_date order:**
- Files: `src/data/postprocess.py:82-104`
- Why fragile: Sorting is purely by `effective_date` (a string comparison, not validated as ISO format) — if the LLM extraction produces a malformed or missing `effective_date`, the sort order (and therefore which prior event a resume inherits its type from) silently shifts, potentially reclassifying resumes incorrectly. There is no validation that `effective_date` values are well-formed dates before this sort.
- Safe modification: Add explicit date-format validation before/during `dedup_records`/`fix_resume_type` and treat rows with malformed `effective_date` as errors requiring manual review rather than allowing them to participate in string-sorted logic.
- Test coverage: Covered at a basic level by `tests/test_announcement_processor.py:220` (`fix_resume_type`), but not for malformed-date edge cases.

**LLM extraction JSON parsing is permissive and silently drops malformed output:**
- Files: `src/data/llm_client.py:156-182`
- Why fragile: `_parse_response()` falls back to substring extraction (`raw.find("[")` / `raw.rfind("]")`) when direct `json.loads` fails, and returns an empty list (`[]`) on any unparseable response with no logging of the raw failure content and no distinction from "the announcement legitimately contained no restriction data." A parsing failure and a genuinely empty announcement are indistinguishable downstream — both silently contribute zero records.
- Safe modification: Log the raw unparseable response (truncated) at `WARNING` level when the JSON extraction ultimately fails, and consider marking such PDFs distinctly (e.g. `parse_failed_malformed_json`) rather than lumping them with `processed`/successfully-empty results in `ProgressTracker`.
- Test coverage: `tests/test_llm_client.py` (149 lines) covers some response-parsing cases; verify it includes the malformed-JSON-fallback path and the "genuinely empty" path as distinct assertions.

## Scaling Limits

**Kimi API concurrency (`DEFAULT_CONCURRENCY = 50`) is a hardcoded constant with no adaptive backpressure:**
- Current capacity: 50 concurrent file-upload + chat-completion requests (`src/data/announcement_processor.py:32`).
- Limit: No mechanism to reduce concurrency dynamically if the Moonshot API starts rate-limiting or erroring at scale; a fixed semaphore either works or floods failures into `tracker.failed`.
- Scaling path: Add adaptive concurrency (e.g. reduce semaphore permits on repeated 429s) or at minimum make `DEFAULT_CONCURRENCY` configurable via env var / CLI flag for different API tiers (partially already configurable via `scripts/parse_announcements.py --concurrency`, but no automatic tuning).

## Dependencies at Risk

**akshare (`ak.fund_open_fund_info_em`) is an unofficial scraping-style wrapper around Eastmoney's public web APIs, not a stable documented API:**
- Risk: akshare endpoints for fund NAV data are known in the broader ecosystem to change response schema/column names without notice (source-site HTML/JSON structure changes upstream). `_get_nav_data()` hardcodes expected column names `净值日期`/`单位净值` (`src/data/downloader.py:191-192`) with no schema validation — if akshare/Eastmoney change these, the rename silently fails to match and downstream code will KeyError or silently produce empty/garbage NAV data depending on pandas behavior.
- Impact: Since NAV data drives PnL calculations directly, an unnoticed akshare schema change could reintroduce PnL-inflation-style bugs similar to `89830c8`, but for price data instead of restriction data.
- Migration plan: Add a schema assertion (`assert set(expected_cols).issubset(df.columns)`) immediately after the akshare call with a clear error message, so schema drift fails loudly instead of silently.

## Test Coverage Gaps

**`src/data/postprocess.py` — no dedicated test file; holiday-resume and synthetic-suspend fix logic (`89830c8`) is entirely untested.**
- What's not tested: `_is_holiday_resume()` classification edge cases; synthetic interval generation in `build_limit_events()`; `validate()` output correctness; `write_limit_events()` table-recreation behavior.
- Files: `src/data/postprocess.py`
- Risk: Highest — this is the exact module responsible for the ~7x PnL inflation bug found post-hoc; no regression safety net exists.
- Priority: High.

**`src/data/llm_client.py` — response-parsing fallback paths and network-error handling under-tested relative to code size/risk.**
- What's not tested (needs verification against current `tests/test_llm_client.py`, 149 lines): malformed-JSON raw-response logging, `get_file_content` HTTP error propagation, `delete_file` silent-failure behavior.
- Files: `src/data/llm_client.py`
- Risk: Medium — silent data loss (empty record list) is hard to detect without dedicated tests distinguishing "truly empty" vs. "parse failed."
- Priority: Medium.

**akshare-based `_get_nav_data()` has no tests exercising column-rename/schema-drift failure modes.**
- What's not tested: Behavior when akshare returns unexpected columns, empty frames, or NaN-heavy `nav` values after `pd.to_numeric(..., errors="coerce")`.
- Files: `src/data/downloader.py:169-203`
- Risk: Medium — schema drift is an external/upstream risk, but the code offers zero defense against it today.
- Priority: Medium.

---

*Concerns audit: 2026-08-18*
