> **SUPERSEDED by `PLAN-m2-hardening.md`.** Retained for its derivations and
> source citations. Do not implement from this document — the retry budget,
> escalation ladder, and demo-versus-experiment policy split here have all been
> revised.

# M2 Failure Modes — Gap Analysis & Handling Protocol

**Companion to** `PLAN-m2-transport-hardening.md`. That document covers the
two-poll transport; this one covers what happens when the agent call itself
fails.

**ID convention:** `F-*` for findings, `W-*` continues the shared work-item
namespace from the transport plan.

**Design principles (stated by Edward, adopted here):**

1. Every failure is published to the log.
2. **No silent failsafe.** A breaking issue fails loudly and reports clearly.
   A run that failed must not look like a run that completed.
3. **No pseudo-infinite retry.** Retry masks root causes and causes token
   runoff.
4. Failures are **typed**, and type determines protocol. Some classes are
   retried once; some are never retried.

---

## Headline findings

### F-A — `estimate()` has exactly one error class

`live_estimator.py:301` catches `KeyError, ValueError, AssertionError,
RuntimeError` in a **single handler**, and `_run_provider` raises `RuntimeError`
for *every* provider failure regardless of cause (`:181`, `:199` — both just
wrap `returncode` + truncated stderr).

Consequently these are all handled identically — retry twice, then salvage, then
neutral decline:

| Actual cause | Current treatment |
|---|---|
| Network / connection drop | retried ×2 |
| Expired or invalid API key | retried ×2 |
| **Quota / token limit exhausted** | **retried ×2** |
| Rate limit (429) | retried ×2 |
| Moderation refusal | retried ×2 |
| Malformed JSON | retried ×2 |
| Schema / slot violation | retried ×2 |

The third row directly violates principle 4. There is currently **no mechanism
capable of expressing "do not retry this"** — the classification does not exist.

---

### F-B — The subprocess provider interface destroys error structure

`_run_provider` (`:171-203`) shells out to `codex exec` and collapses the entire
failure surface to `(returncode, stderr[:1000])`. An SDK call would yield an HTTP
status, a structured error code, and `retry-after`; a subprocess yields an
integer and a truncated string.

**This is the central architectural decision for W-6/W-13.** Classification
requires either:

- **(a)** parsing `stderr` text for known patterns — brittle, breaks on provider
  CLI version changes, and silently degrades to "unknown" when it breaks; or
- **(b)** changing the provider interface to one that preserves structured
  errors — an SDK path, or a wrapper contract where the provider command emits a
  structured error document on a known channel.

Option (b) is more work and is the correct answer if error handling is to be
trustworthy. Option (a) is defensible *only* if the "unknown" bucket defaults to
**non-retryable + abort**, so a classification failure fails safe rather than
retrying blindly. This decision should be made explicitly and recorded — it
gates most of the rest of this plan.

---

### F-C — Failure never reaches the run verdict

The full silent-success chain, verified:

1. `estimate()` exhausts retries → `trace["neutral_reason"] = "provider retries
   exhausted"` → returns `_neutral(...)` (`:313-314`)
2. `_neutral` → `response_template.assemble(..., decline=True)` → sets
   `doc["pass"] = True` (`response_template.py:187`)
3. watcher writes it as an ordinary `UtilityResponse` (`llmoses_watcher.py:341`)
4. `_ingest_utilities` reads `pass:true` → logs `utility_ingest decline=True`
   (`state_builder.py:936-941`)
5. run completes; `flush_terminal` writes `capture_failures` (`:553`) — which was
   **never incremented for any estimator failure**

**Result: a run in which every single generation failed on expired credentials
produces a `terminal.json` with `capture_failures: {}` and a clean exit.** It is
indistinguishable from a run where a healthy agent chose to abstain each
generation.

This is exactly the "quietly fail and act like the run completed" outcome that
principle 2 forbids. It is the most important finding in this document.

---

### F-D — Retry budget is per-generation; the requested policy is inexpressible

`estimate()` holds no cross-generation state. Each call starts a fresh budget of
`_DEFAULT_RETRIES = 2`.

"Two network failures in a row should end the run" **cannot currently be
written** — there is nowhere to store "in a row." This is an architectural gap,
not merely a policy gap.

**Token-runoff arithmetic.** A 50-generation run against dead credentials issues
`50 × 3 = 150` provider calls. Each prompt carries the rendered
`ESTIMATOR_PROMPT.md`, the full JSON schema, the slots table, and an evidence
digest capped at 30 rows across three lists (`:46-66`, `:91-109`) — and the
retry path **re-sends the entire prompt** with the error appended (`:104-108`).
That is the runoff scenario, structurally present today.

---

### F-E — Default timeouts are mutually inconsistent; live mode is broken by default

| Setting | Default | Source |
|---|---|---|
| `LLMOSES_LIVE_TIMEOUT_S` | 240 s **per attempt** | `live_estimator.py:21` |
| `LLMOSES_LIVE_RETRIES` | 2 → **3 attempts** | `live_estimator.py:22` |
| Estimator worst case | **720 s** | derived |
| `LLMOSES_RESPONSE_TIMEOUT_S` | **30 s** | `state_builder.py:120` |

With stock defaults MOSES abandons the wait at 30 s, applies stale guidance
(W-1), and the watcher's eventual response is never read. Even a *single
successful* call exceeding 30 s — routine for `gpt-5.5` at medium effort —
breaks the handshake.

It works today only because `live_agent_demo.sh:96` hand-sets
`LLMOSES_RESPONSE_TIMEOUT_S=900`. **That 900 is a magic number encoding an
invariant that nothing enforces.** `lambda_sweep_demo.sh:83` and
`utility_policy_test.sh:143` both use 30 s — correct for their mock modes, and
silently wrong the moment anyone runs live under them or raises the retry count.

**This upgrades W-4 from MEDIUM to HIGH.**

---

### F-F — Moderation refusals are retried, and are not retryable

A moderation refusal typically exits 0 with prose rather than JSON.
`_extract_json_object` finds no `{` → `ValueError("provider output contained no
JSON object")` (`:117`) → retried with the error appended → same refusal →
decline. Three calls spent on a deterministic outcome, then swallowed silently
per F-C.

---

### F-G — Salvage can mask a systematically wrong response

`_salvage_values` (`:221-251`) drops offending keys one at a time until
`assemble` succeeds. A response salvaged from 40 slots down to 2 still returns
as a **non-decline** and is indistinguishable at the ingest layer from a
complete response. The same concern is already raised for replay in
`HANDOFF-milestone2-followups.md:107-118`; it applies equally to live
experimental validity.

The watcher has a *second*, independent salvage layer
(`llmoses_watcher.py:320-337`) with the same property.

---

## Milestone 1 findings

### F-H — `_section` discards the exception detail

`state_builder.py:634-644` increments `_capture_failures[name]`, appends to
`failed_sections`, and writes the exception to **stderr only**. `_log_event` is
never called, so the error text never enters `moses_native_log.jsonl`.

Post-hoc analysis of a completed run can therefore see *that* `atom_evidence`
failed 12 times but not *why*. For a submission artefact this is a real gap —
the run directory is the deliverable, and stderr is not in it.

**Fix:** `_section` emits a `section_failed` row carrying `repr(e)`.

---

### F-I — `_log_event` silently swallows its own failures

`state_builder.py:837-838` is a bare `except: pass`. Defensible — logging must
never kill a run — but it means the audit log can be silently incomplete, and
the audit log is what the whole verification story rests on.

**Fix:** set a run-scoped `logging_degraded` flag surfaced in `terminal.json`.
Cheap, and converts an invisible failure into a visible one.

---

### F-J — `_ingest_utilities` error path is a second instance of W-1

`state_builder.py:924-926` logs `utility_ingest_error` and returns **without
clearing `_pending_utilities`**. A corrupt or unreadable utilities file
therefore leaves the previous generation's guidance live — the same stale-application
class as the timeout path.

**Covered by W-2's fence.** Recorded here so it is not treated as a separate fix.

---

## Proposed failure taxonomy and protocol

Escalation model: **per-class, run-scoped, consecutive-failure counter.**
Retryable classes get one in-generation retry; two *consecutive generations*
failing the same retryable class ends the run. Non-retryable classes end the run
immediately.

| # | Failure class | Detection | Retry | Escalation |
|---|---|---|---|---|
| 1 | Network / connection | provider transport | 1 | 2 consecutive → **abort run** |
| 2 | Auth (invalid/expired key) | provider auth error | **none** | **abort immediately** |
| 3 | Quota / credit exhausted | provider quota error | **none** | **abort immediately** |
| 4 | Rate limit (429) | provider throttle | 1, with backoff | 2 consecutive → abort |
| 5 | Provider timeout | `subprocess.TimeoutExpired` | 1 | 2 consecutive → abort |
| 6 | Moderation / refusal | exit 0, no JSON | **none** | record; policy-dependent |
| 7 | Malformed output | parse failure | 1 | 2 consecutive → abort |
| 8 | Schema / slot violation | `assemble` raises | 1 (error fed back) | 2 consecutive → abort |
| 9 | Salvage required | salvage dropped ≥1 key | n/a | record, count toward validity |
| 10 | Deliberate abstention | agent `204` | n/a | **not a failure** — must be distinguishable |
| 11 | Watcher process death | heartbeat static | n/a | abort (W-3) |
| 12 | MOSES-side response timeout | deadline exceeded | n/a | abort or degrade per policy (W-4) |

**Two distinctions that are easy to get wrong and matter here:**

- **Rate limit (4) is transient; quota (3) is terminal.** Collapsing them means
  either retrying a dead account or abandoning a recoverable throttle. They must
  be separated at classification time.
- **Abstention (10) is not failure.** Row 10 is the whole reason W-5's status
  taxonomy exists — without it, rows 1-9 are indistinguishable from a healthy
  agent having nothing to say.

**Every class writes:** a native-log row with the class and detail, a per-code
`capture_failures` increment, and — on abort — a terminal verdict with reason.

---

## New work items

| ID | Item | Depends on | Severity |
|---|---|---|---|
| **W-13** | Classify provider errors at `_run_provider`; replace the single `RuntimeError` with a typed error carrying class + retryable bit. **Requires the F-B interface decision first.** Unknown class must default to non-retryable + abort. | F-B decision | HIGH |
| **W-14** | Run-scoped consecutive-failure state + escalation ladder. New state; does not exist today (F-D). | W-13 | HIGH |
| **W-15** | Estimator failures must increment `capture_failures` and reach `terminal.json`. Closes F-C. | W-5 | HIGH |
| **W-16** | Enforce the timeout invariant at startup: `LIVE_TIMEOUT_S × (RETRIES+1) < RESPONSE_TIMEOUT_S`. Fail fast with a clear message rather than relying on hand-set magic numbers. Closes F-E. | — | HIGH |
| **W-17** | `_section` logs exception detail to the native log (F-H); `_log_event` sets `logging_degraded` (F-I). M1 hygiene. | — | MEDIUM |
| **W-18** | Salvage becomes a first-class recorded outcome with a degradation measure (slots requested vs. survived), not a silent repair. Both salvage layers. Closes F-G. | W-5 | MEDIUM |
| **W-19** | `run_verdict` field in `terminal.json`: `ok / degraded / aborted` + reason. | W-15 | HIGH |
| **W-20** | **Abort channel from watcher to MOSES.** No such channel exists — `CONTROL/stop` stops the *watcher*; there is no reverse. Without it, "end the run and report" is unimplementable: MOSES would merely time out and continue. Proposal: watcher writes `CONTROL/abort` with a reason document; `await_response` checks it each poll iteration and exits non-zero. | W-3 | HIGH |

---

## The single most important addition for M2 submission

**W-19 (`run_verdict`).** Today nothing in the run directory states whether the
run is valid. A reviewer cannot distinguish a clean run from one where every
generation failed, without reading stderr that was never captured.

Everything else in this document is machinery; `run_verdict` is the output that
makes the machinery legible to someone assessing the submission.

---

## Open decisions for review

1. **F-B: which provider interface?** Brittle stderr parsing with fail-safe
   defaults, or a structured-error provider contract. Gates W-13.
2. **Class 6 (moderation): abort or record-and-continue?** Arguably a legitimate
   agent outcome on some states rather than a system failure.
3. **Retry count.** The taxonomy above proposes 1 retry for retryable classes
   (down from the current 2) on the grounds that constrained/tool-call
   generation should make format failures rare. Confirm.
4. **Does class 12 abort or degrade?** Suggest policy-flagged, matching W-7:
   abort for experiment cells, degrade for demos.
