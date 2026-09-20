> **SUPERSEDED by `PLAN-m2-hardening.md`.** Retained for its derivations and
> source citations. Do not implement from this document — several items were
> re-scoped, W-16's proposed deletion was reversed by probe, and the
> abort/degrade policy here is obsolete.

# M2 Transport Hardening — Issue Ledger & Development Plan

**Status:** draft, in progress. Scope: the two-poll handshake between MOSES
(`state_builder.await_response`) and the shadow-agent watcher
(`llmoses_watcher.py`).

**ID convention:** provisional `W-*` IDs, to be renumbered into the `D-*`
decision log when this plan is accepted. Each entry records *issue*, *why it is
a problem*, and *resolution*.

**Session ground rules:** analysis only, no code changes made while drafting.
All findings verified against source; `file:line` citations throughout.

---

## Decision record: the transport mechanism stays polling

**W-11 — inotify / push notification: rejected for M2.**

Considered replacing the 100 ms watcher scan and the 50 ms MOSES block with an
OS-native file-event mechanism (the existing TODO at `llmoses_watcher.py:22-24`
proposes exactly this).

**Rejected, on two grounds:**

1. The run directory is a **bind mount**, and the blocking side (MOSES) runs
   **inside the container**. Host→container inotify propagation across
   virtiofs / gRPC-FUSE is unreliable-to-absent. A pure-push design would
   silently never fire in the dev configuration and hang every generation until
   timeout — a severe regression delivered in the name of robustness.
2. Latency is not a concern for an experimental harness at this stage. The
   optimisation buys nothing currently wanted.

Additionally, `IN_Q_OVERFLOW` means inotify drops events under load, so any
correct push design must retain a reconciliation scan regardless. Push can
never be the correctness mechanism — only an accelerator.

**Retained conclusion:** polling remains the correctness mechanism. The
restructure being pursued is to the *protocol semantics*, not the wake-up
mechanism.

**Revisit only if:** SNET deploys machine-local (agent + MOSES on one VM, no
bind mount) *and* latency becomes a measured constraint.

---

## Keystone item

### W-2 — No idempotency fence on utility application

**Issue.** `_pending_utilities` has no validity window. `_utility_gen`
(`state_builder.py:107`) is written on ingest (`:937`, `:1053`) but read as a
*guard* in exactly one place — the complexity-ratio lever's
`_cratio_applied_for` check at `:1447-1450`. At every other site
(`:1133`, `:1197`, `:1225`, `:1389`, `:1469`) it is a **logging field only**.
`_lever_on` (`:863-872`) gates on buffer non-emptiness, `_APPLY_LEVERS`, and
`_LEVER_WEIGHTS` — never on generation.

**Why it is a problem.** The protocol is not idempotent. Applying the same
response twice is not a no-op; applying a stale response is indistinguishable
from applying a fresh one. Replay-based paired comparisons (HANDOFF work item 1)
rest on determinism this does not provide. The freshness invariant is currently
enforced at one call site as a *side effect of an unrelated concern* (cumulative
ratio compounding) rather than centrally.

**Resolution.** Promote the fence from one lever to the buffer itself, keyed on
`(run_seq, gen)`:

- ingest for generation *g* sets buffer and fence = *g*
- re-ingest of the same `(run_seq, g)` is a no-op
- ingest of a generation older than the fence is rejected (monotonicity)
- `_lever_on` asserts the fence matches the expected offset from the current
  generation; any mismatch → native behaviour + loud log
- generalises `_cratio_applied_for`; that guard becomes a special case rather
  than a one-off

**Why this is the keystone.** It subsumes W-1 entirely, delivers the
idempotency goal, and makes hook re-entry harmless *by construction* — which is
why the backtracking probe's residual scope (untested: multi-deme
materialisation, strategy problem type) does not need widening. Implement
first; several other items assume it.

---

## Correctness defects

### W-1 — Stale guidance applied after response timeout

**Issue.** On timeout, `await_response` returns at `state_builder.py:586`
without calling `_ingest_utilities`. `_pending_utilities` therefore retains the
*previous* generation's response, and `_lever_on` happily applies it.

**Why it is a problem.** The function's own docstring (`:566-568`) states that a
broken or absent responder "must degrade to native, never deadlock." It does not
degrade to native — **it degrades to stale.** Implementation contradicts its
documented contract. Four of five levers are affected; the complexity-ratio
lever is *accidentally* immune via `_cratio_applied_for`. A timeout during a
λ-sweep silently contaminates the cell and the run still looks complete.

**Evidence already on disk.** Every `bias_applied` row carries `response_gen`.
On an affected run the log shows guidance applied at generation G+2 carrying
`response_gen=G`. Nothing asserts on it.

**Resolution.** Covered by W-2's fence. Add a regression test that reverse-checks
— it must fail against the pre-fence code.

**Severity:** HIGH — silent, contaminating, already instrumented.

---

### W-3 — Dead watcher indistinguishable from slow watcher

**Issue.** Timeout is the only failure signal. There is no liveness channel.
Flagged independently in `HANDOFF-milestone2-followups.md:123`
(`LLMOSES_RESPONSE_TIMEOUT_S` masks a dead watcher as a timeout).

**Why it is a problem.** A watcher that dies at generation 3 of a 50-generation
run causes MOSES to burn `30 s × 47` ≈ 23 minutes of dead waiting, producing a
garbage run, reported only in `capture_failures` at termination. No circuit
breaker. This is the most practically painful defect in the current design.

**Resolution.** A heartbeat file under `CONTROL/`, **separate from the
sentinels**, giving a three-way discrimination in the MOSES wait:

| Observation | Meaning | Action |
|---|---|---|
| response sentinel appears | success | proceed |
| heartbeat advancing, no sentinel past deadline | genuinely slow | record honestly; policy-dependent |
| heartbeat static | watcher dead | abort now, non-zero exit |

**Critical design constraint — do not use wall-clock deltas.** The watcher and
MOSES may sit on opposite sides of the container boundary, i.e. in different
clock domains, and Docker Desktop VM clock drift after host sleep is a known
problem. Wall-clock liveness would produce phantom dead-watcher aborts after
every laptop lid close. Instead the heartbeat carries a **monotonically
increasing counter**, and the reader asserts the counter *advanced* across N
observations. Counter comparison is clock-free and immune to the entire class.

**Severity:** HIGH.

---

### W-4 — Fixed 30 s deadline unsuited to a live estimator with a retry budget

**Issue.** `_RESP_TIMEOUT_S` defaults to 30 s (`state_builder.py:120`). The
watcher's own comment (`llmoses_watcher.py:309-313`) states a live agent retries
internally before falling through to salvage.

**Why it is a problem.** A retry chain can plausibly exceed 30 s, so the timeout
can fire on a *healthy* system, triggering W-1's stale application on a run where
nothing was actually wrong.

**Resolution.** Distinguish per-attempt timeout from total budget; size the
MOSES deadline against the watcher's worst-case retry chain rather than
independently. Depends on W-6.

**Severity:** MEDIUM.

---

## Failure-signalling design

### W-5 — `pass:true` is overloaded; three distinct events collapse into one signal

**Issue.** `pass:true` currently means all of:

1. the agent deliberately abstained (healthy, nothing actionable)
2. the agent failed internally
3. the provider was unreachable and the watcher **synthesised** a neutral
   (`llmoses_watcher.py:304-307`)

These are indistinguishable downstream.

**Why it is a problem.** This *is* the silent-failure mode the redesign is meant
to eliminate — the API equivalent of going quiet instead of returning a status
code. An invalid experiment cell is indistinguishable from a valid abstaining one.

**Resolution — status taxonomy, with two authorship layers.**

The essential constraint: **the model cannot author most of these.** Three
failure domains with different authors:

| Domain | Example | Who reports |
|---|---|---|
| Transport / provider | connection drop, expired key, rate limit, provider timeout | **wrapper only** — the model never ran |
| Format | model responded, JSON malformed or schema-invalid | wrapper detects, model caused |
| Semantic | input insufficient, no actionable signal, low confidence | **model self-reports** |

Proposed codes:

- `200` — guidance provided
- `204` — deliberate abstention; agent healthy
- `422` — input unusable (state incomplete, alphabet mismatch,
  `capture_status.ok` false). Agent healthy, emitter supplied bad input.
  **Not retryable** — the input will not change.
- `500` — agent's own reasoning failed
- `503` / `504` — provider unreachable / timed out. **Wrapper-authored.
  Retryable.**

Implemented as a `status` field the model fills, plus a wrapper envelope that
stamps transport failures when the model never answered. `AgentTrace` is the
natural home for the wrapper layer.

**Two design points that matter more than the taxonomy:**

1. **Make the error path cheaper than the success path.** If the only way to
   signal failure is a complete valid nine-key `UtilityResponse` with
   `pass:true`, a confused model will emit malformed JSON before it emits a
   correct decline. The error document must be minimal —
   `{"status", "code", "detail"}` — so that declining is *easier* than
   hallucinating. Schema design doing prompt engineering's job.
2. **Carry a `retryable` bit** (see W-6).

**Severity:** HIGH (design).

---

### W-6 — Retry budget undifferentiated by error class

**Issue.** Retry is currently uniform.

**Why it is a problem.** Retrying a `422` burns budget on an input that cannot
change; retrying a `503` is correct. Undifferentiated retry does both wrong.

**Resolution.** The `retryable` bit from W-5's taxonomy drives the watcher's
retry policy. Feeds W-4's deadline sizing.

**Severity:** MEDIUM.

---

### W-7 — Errors do not survive to the analysis layer

**Issue.** A failure becomes a neutral response indistinguishable from a genuine
abstention. `capture_failures` records `response_timeout` as a single
undifferentiated count (`state_builder.py:578-579`, surfaced at `:553`).

**Why it is a problem.** A λ-sweep cell where the agent `500`'d on 30 % of
generations is not a valid data point, but today it looks like a completed run
and would be averaged in silently. Directly connected to the HANDOFF's replay
integrity concerns.

**Resolution.**

- per-code breakdown in `capture_failures`, carried through to `terminal.json`
- **policy flag, not hardcoded behaviour**: abort loudly for experiment cells,
  degrade to native for demo runs
- implement this as the *same* strict/lenient mechanism the HANDOFF proposes for
  replay (`HANDOFF-milestone2-followups.md:112-125`) rather than a second
  parallel one

**Severity:** HIGH for experimental validity.

---

### W-8 — Agent response-contract skill

**Issue.** Nothing currently teaches the agent the response schema or the
decline/error taxonomy.

**Resolution.** A skill under `llmoses/skills/` (alongside the existing
`ACTION_LEVERS.md` and `RUN_DIRECTORY.md`) covering the response contract,
worked examples, the W-5 status codes, and explicit "when to abstain vs. when to
error" guidance.

**Scope honesty.** A skill addresses the *format* and *semantic* domains only.
It cannot help with transport failures — a skill cannot instruct a model that
was never reached. This improves the failure surface; it does not solve it.

**Severity:** MEDIUM.

---

## Hygiene / latent

### W-9 — Sentinel and heartbeat separation; atomicity scope

**Not a current defect.** The sentinel files (`ready/run-N-step-G` at
`state_builder.py:814-816`, `response/run-N-step-G` at
`llmoses_watcher.py:406-408`) are written non-atomically and contain a timestamp
nothing reads. Since only *existence* is checked, atomicity is irrelevant — a
zero-byte file satisfies `os.path.exists` identically. Correct as written.

**The risk is one W-3 introduces.** Once a liveness signal carries content that
is read, a reader can observe a created-but-not-yet-written file, parse it empty,
and interpret that as a stale heartbeat → spurious dead-watcher abort.

**Resolution — keep the two roles separate:**

- **Sentinel:** edge-triggered, write-once, existence-only, means "this step is
  complete." Keep it dumb. Do **not** overload it with heartbeat duty —
  appending timestamps couples two different lifetimes and reintroduces a parse
  race into the one signal currently immune to it.
- **Heartbeat:** level-triggered, rewritten periodically, content-bearing,
  written via the existing tmp + `os.replace` pattern. Counter-based per W-3.

**Severity:** LOW now; MEDIUM once W-3 lands.

---

### W-10 — fsync durability

**Issue.** `os.replace` gives atomicity against concurrent readers but not
durability against host crash. No `fsync` anywhere.

**Why it is a problem.** Only for long unattended runs — losing hour 6 of an
8-hour sweep. On a dev laptop, crash-during-run means rerun.

**Resolution.** Implement behind a flag, default off; document when to enable
(long unattended SNET sweeps). Not worth unconditional cost.

**Severity:** LOW.

---

### W-12 — Transport cost dominates the test battery

**Issue.** ~75 ms average round-trip polling latency per generation. Negligible
against a multi-second live LLM call; **dominant** in the 36-assertion battery
and λ-sweeps where real work is sub-millisecond.

**Why it is a problem.** Test-suite speed only. This is the inversion worth
noting: polling is a test-runtime problem, not a production one.

**Resolution (optional).** The mock modes are pure deterministic functions of
`(state, run_config, gen)`, so a direct in-process dispatch mode would remove
IPC from the test path entirely. **Caveat:** that path would no longer exercise
the transport, so at least one transport-level integration test must be
retained. Raised as an option, not a recommendation.

**Severity:** LOW.

---

## Implementation order

1. **W-2** (fence) — keystone; subsumes W-1, delivers idempotency, absorbs
   re-entry risk
2. **W-5** (status taxonomy) — W-6 and W-7 both depend on the code set
3. **W-6** (retryable-driven retry), then **W-4** (deadline sized to retry budget)
4. **W-3** (heartbeat + escalation) with **W-9** (sentinel/heartbeat separation)
5. **W-7** (error survival to `terminal.json`; strict/lenient policy flag shared
   with replay)
6. **W-8** (agent skill)
7. **W-10**, **W-12** — optional / deferred

---

## Closed

- **W-11** — inotify rejected; polling retained as correctness mechanism. See
  decision record above.
- **Re-entry hypothesis** — dead for the tested seam. Probe showed exactly one
  `flush_gen` and one `await_response` per generation across all three
  configurations (await enabled + live watcher; await disabled; await enabled +
  no watcher + 1 s timeout), with no correlation to `nDeme` or candidate count.
  Neither the blocking response nor its timeout return triggers PeTTa goal
  retry. `_cratio_applied_for` is confirmed consistent with protection against
  documented cumulative compounding, not hook-chain re-reduction.
  Residual untested scope (multi-deme materialisation, strategy problem type) is
  absorbed by W-2 rather than probed further.

---

## Deferred / out of scope for this thread

- **Deme capture fidelity (M1, not M2).** The probe fixture requested
  `nDeme=2` but captured 1 deme in all three generations, including generation 3
  where 2 exemplar candidates were present
  (`llmoses/llmoses-tests/boolean_state_test.metta:125`). This may be correct —
  `nDeme` is a target and deme creation depends on selection — but captured deme
  count feeds the state document the agent consumes, so a discrepancy would be a
  capture-fidelity issue. Confirm separately.
