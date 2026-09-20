# M2 Hardening — Consolidated Development Plan

**Supersedes** `PLAN-m2-transport-hardening.md` and `PLAN-m2-failure-modes.md`.
Both are retained for their derivations; this document is authoritative.

**ID convention:** `W-*`, single namespace. To be renumbered into the `D-*`
decision log on acceptance.

**Provenance:** every finding was verified against source with `file:line`
citations, or established by probe. Both probes are recorded in §9.

**Scope:** all items are M2. The grant has four milestones and two development
milestones; M3 runs the experiments and M4 reports conclusions. There is no
later implementation milestone to defer into.

---

## 1. Architecture

### 1.1 One loop, one contract, a pluggable responder

MOSES emits state, blocks, and resumes when a response appears. It cannot
observe *who* wrote the response and does not need to. Every responder satisfies
exactly one contract:

1. observe `ready/run-<seq>-step-<g>`
2. read `state/run-<seq>/step-<g>.json` and `run_config.json`
3. write `utilities/run-<seq>/step-<g>.json` (a valid `UtilityResponse`)
4. write `traces/run-<seq>/step-<g>.json` (an `AgentTrace`)
5. write `response/run-<seq>-step-<g>` **last**
6. move the consumed `ready/` marker to `ready/.consumed/`

Step 5's ordering is the barrier: its presence guarantees 3 and 4 are complete.
Step 6 is currently performed only by the watcher (`llmoses_watcher.py:410`); any
responder must also perform it, or a later watcher run against the same directory
reprocesses every step.

The estimator is **already pluggable in the code** —
`LLMOSES_MOCK_UTILITY_MODE` selects among fourteen values including `live`. The
file seam makes responder identity invisible to MOSES, which the design spec
already states (`v20_work.md:934`: the handshake makes process placement free).

### 1.2 Responder options

**Agent-orchestrated (primary).** A coding agent starts the container, triggers
the run, reads emitted state, produces the estimate itself, and writes the
response. It supervises MOSES as a child job, decides how to interpret failures,
and reports to the user. This is the architecture the project is *for*: the agent
reads evolutionary history across generations and reasons over it.

**Bounded estimator (option and baseline).** `live_estimator.py` — a specified,
minimal, single-call estimator. Not a deployment mode: an *estimator option* the
agent may invoke when it wants an attributable treatment, and a baseline
condition to compare agentic estimation against. It already exists and is
retained unchanged in role, reduced in scope.

### 1.3 Governing rule for every failure decision

**The question is not "whose fault was this" but "does this still allow a
meaningful experimental run".**

Fault attribution is irrelevant. A moderation gate is a legitimate action by a
body we have no line of communication with, and it is *still* a failed run,
because it leaves MOSES executing without the LLM — which is not the experiment.
An outcome outside our control is not thereby an outcome we can accept.

- **`200` (guidance) and `204` (deliberate abstention) continue.** Abstention is
  the agent legitimately choosing native for one generation; the population stays
  sound and the run remains the experiment it claims to be.
- **Everything else aborts**, after at most one retry where retry is justified.

There is **no run-level degradation.** MOSES never proceeds without an estimate
it was supposed to receive. The run either produces its intended mechanism or
exits non-zero.

"Degraded" is reserved for a distinct, *experiment-level* meaning: a run that
completed correctly and whose mechanism worked, but which carries quality
caveats — non-breaking hallucinations, salvage drops, partial slot coverage,
retries that succeeded. That verdict applies uniformly; there is no
demo-versus-experiment policy split.

### 1.4 Record: the two-mode split was withdrawn

An earlier revision of this plan specified two co-equal deployment modes with
duplicated failure machinery. That was over-engineering, introduced because the
plan had been designed around an unattended watcher and the agent-orchestrated
vision was bolted on as a second mode rather than recognised as superseding it.
The arguments given for the split did not survive scrutiny:

- **Auditability.** Claimed the bounded estimator captures reasoning that an
  agent would not. The probe (§5) disproves it: `reasoning_output_tokens: 184`
  with `reasoning_event_count: 0` — reasoning tokens were consumed and **no
  reasoning content was emitted**. The bounded path captures the *answer*, not
  the reasoning. An agent that writes a rationale is strictly richer. The
  load-bearing audit trail — `bias_applied` rows, lever application counts, state
  extractions, `run_verdict` — is written by `state_builder.py`, is deterministic,
  and is unforgeable by the agent in either case.
- **Reproducibility for λ-sweeps.** The bounded estimator is an LLM call and is
  not reproducible either. Reproducibility is delivered by *replay*
  (`HANDOFF-milestone2-followups.md` work item 1), which operates on response
  files and is responder-agnostic. Parallel agent sessions serve sweeps fine.
  The residual difference is cost, not capability.
- **Context window.** The bounded path "solves" context by discarding continuity
  between generations — but cross-generation continuity is the contribution, not
  an obstacle. Context strategy is an experimental variable to ablate (W-22), not
  a constraint to bake into the architecture.

**Consequence:** four items specified for unattended-watcher robustness
(W-13, W-14, W-16, W-3) are substantially reduced, and supervision becomes an
explicit item (W-27) rather than an emergent property of the watcher.

**Separation of duties that replaces the split:** the estimator's job is to
**report accurately**; the supervisor's job is to **decide**.

---

## 2. Shared foundation

Mode-independent. These land first; everything else depends on them.

### W-2 — Generation fence on utility application `[KEYSTONE]`

**Issue.** `_pending_utilities` has no validity window. `_utility_gen`
(`state_builder.py:107`) is written on ingest (`:937`, `:1053`) but read as a
guard in exactly one place — `_cratio_applied_for` at `:1447-1450`. Everywhere
else (`:1133`, `:1197`, `:1225`, `:1389`, `:1469`) it is a logging field only.
`_lever_on` (`:863-872`) never checks generation.

**Consequences, all one bug:**

- **W-1 (stale-on-timeout).** On timeout `await_response` returns at `:586`
  without ingesting, leaving the *previous* generation's guidance live. The
  docstring at `:566-568` promises degradation to native; the code degrades to
  **stale**. Four of five levers affected; complexity-ratio is accidentally
  immune via `_cratio_applied_for`.
- **W-1b (stale-on-parse-error).** `_ingest_utilities` at `:924-926` logs
  `utility_ingest_error` and returns **without clearing the buffer**.
- **Non-idempotency.** Re-applying a response is not a no-op, so replay-based
  paired comparisons are not reproducible.

**Resolution.** Fence the buffer on `(run_seq, gen)`:

- ingest for generation *g* sets buffer and fence = *g*
- re-ingest of the same key is a no-op
- ingest of a generation older than the fence is rejected
- `_lever_on` asserts the fence is **exactly one generation behind** current
- `_cratio_applied_for` becomes a special case of the general rule

**The offset is exactly 1, and a violation is fatal, not a fallback.** MOSES's
meta-loop — like essentially every evolutionary algorithm — advances
generation-to-generation, so a response ingested at *G* is applied at *G+1* and
nowhere else. Ingesting from *G−2* and applying at *G+1* would mean the meta-loop
itself is broken in a way that invalidates every result the project produces. The
fence therefore **aborts** on offset ≠ 1 rather than falling back to native.

This is clean *because* of §1.3: since a missing estimate aborts the run,
staleness cannot arise in a run that is still alive, so the check is an assertion
rather than a recovery path.

**Test.** Regression test must reverse-check — it has to fail against pre-fence
code.

**Severity:** HIGH.

---

### W-5 — Response status taxonomy

**Issue.** `pass:true` currently means all of: deliberate abstention; agent
internal failure; and provider death with a synthesised neutral
(`live_estimator.py:313-314` → `response_template.assemble(decline=True)` →
`response_template.py:187`). Three unrelated events, one signal.

**Why it is load-bearing.** It is the contract every responder writes to, and it
is what makes a run scientifically assessable: **abstention preserves validity,
failure destroys it.** A `204` is the agent legitimately choosing native and the
population stays sound; a `500` means guidance that should have existed did not,
and — because MOSES is evolutionary — that contaminates every subsequent
generation rather than averaging out.

**Resolution — additive metadata, not a new communication model.** `pass` keeps
its current meaning and continues to carry the continue/decline decision. A
`status` field is **appended alongside** it to say *why*:

| Code | Meaning | Author | `pass` | Retryable |
|---|---|---|---|---|
| `200` | guidance provided | responder | `false` | — |
| `204` | deliberate abstention, healthy | responder | `true` | — |
| `422` | input unusable (incomplete state, alphabet mismatch, `capture_status.ok` false) | responder | `true` | **no** |
| `500` | responder's own reasoning failed | responder | `true` | no |
| `503` / `504` | provider unreachable / timed out | wrapper | `true` | see W-14 |

Per §1.3, only `200` and `204` continue.

**Blast radius — this is why the field is additive.** `UtilityResponse` is
constructed or validated in `response_template.assemble`,
`utility_schema.validate_utility_response`, `_ingest_utilities`, all fourteen
watcher mock modes including `_NEUTRAL_DOC`, and asserted on by the 50-assertion
battery (TRANSPORT 9 + POLICY 41 across 12 phases, post-D-033/034/035).
Replacing `pass` would require changing all of them at once on a system
that currently passes its tests. Appending `status` leaves every existing path
working untouched.

**Adopt `--output-schema`.** Probe Part D confirmed `codex exec` supports it.
Constrained generation should collapse malformed-output and schema-violation
failures close to zero.

**Severity:** HIGH.

---

### W-26 — Fabricated `program_id` detection

**Issue.** Hallucinated program ids are **silently inert**. `_ingest_utilities`
builds its id-keyed maps without any membership check, so a fabricated id enters
the dict, never matches at lookup, and vanishes — no log, no counter, no effect.
This is exactly the phenomenon worth measuring as a research output, and it is
invisible today.

**Three id-bearing channels, all affected:**

| Channel | Source | Note |
|---|---|---|
| `exemplar_utilities` | `state_builder.py:943-949` | — |
| `culling_utilities` | `:950-968` | **`"*"` is a legitimate sentinel** (`:962-967`) meaning newborn default — must be exempted |
| `comparator_bias.program_id_ordering` | `:1024-1028` | — |

**Check against generation *G*'s population, not application-time.** Guidance for
*G* is applied at *G+1*, by which point normal evolutionary churn may
legitimately have culled ids that were real when the responder saw them.
Validating late would count churn as hallucination and the statistic would
measure MOSES dynamics rather than model behaviour. Validate at **ingest**
against `_gs(g)["members"]` — which `_gen[g]` still holds at that point
(`:206-210`; reset only by `begin_gen` / `new_run`), so no extra disk read.

The question is "did this id ever exist in generation *G*", not "was it offered
as a slot". The permissive form is correct.

**Record a rate, not a count.** `unknown_ids / total_ids_supplied`, per channel.
Cap any recorded id sample (~10).

**Behaviour is unchanged** — fabricated entries stay inert exactly as today. A
pure-observation change that cannot regress lever behaviour, making it the
lowest-risk item in the plan and safe to land first.

**Reuse.** The existing `ignored` map has the right shape and is already logged
in the `utility_ingest` row (`:1054-1057`).

**Severity:** HIGH (research output). **No dependencies.**

---

### W-15 — Failures reach `capture_failures`

Responder and estimator failures increment a per-code counter flowing into
`terminal.json`, feeding W-19.

**Verified silent-success chain being closed:** retries exhausted → neutral
decline → `pass:true` → `_ingest_utilities` logs a *decline* (`:936-941`) → run
completes → `capture_failures` **never incremented** (`:553`). A run in which
every generation died on expired credentials produces `capture_failures: {}` and
a clean exit.

**Severity:** HIGH. **Depends on:** W-5.

---

### W-19 — `run_verdict` in `terminal.json`

**Issue.** Nothing in the run directory states whether a run is valid.

| Verdict | Meaning |
|---|---|
| `ok` | completed; mechanism worked; no quality flags |
| `degraded` | completed and mechanically correct, but carrying quality caveats — hallucinations (W-26), salvage drops (W-18), partial coverage, or retries that succeeded |
| `aborted` | exited non-zero. Not a run. |

`degraded` is an **experiment-quality** judgement, never a run-mechanism one.
Computed identically for every run.

**The single most important addition for M2 submission.** Everything else is
machinery; this is what makes the machinery legible to a reviewer who will not
read logs — and stderr, where most failures currently surface, is not captured
into the run directory at all.

**Severity:** HIGH. **Depends on:** W-15.

---

### W-20 — Abort channel (responder → MOSES)

**Issue.** No such channel exists. `CONTROL/stop` stops the *watcher*; nothing
goes the other way. "End the run and report the problem" is unimplementable —
MOSES would merely time out and continue.

**Resolution.** Responder writes `CONTROL/abort` with a reason document;
`await_response` checks it each poll iteration and exits non-zero; the driver
treats it as a failed run.

**Elevated by the architecture change.** This is now the primary mechanism by
which the supervising agent stops a run it has judged unsalvageable. Every
escalation decision in this plan is inert without it.

**Severity:** HIGH.

---

### W-17 — M1 logging gaps

- **`_section` discards exception detail** (`:634-644`): increments the counter,
  appends the section name, writes the exception to **stderr only** —
  `_log_event` is never called. Analysis can see *that* `atom_evidence` failed
  twelve times but not *why*, and stderr is not in the run directory. Fix: emit a
  `section_failed` row carrying `repr(e)`.
- **`_log_event` swallows its own failures** (`:837-838`, bare `except: pass`).
  Correct that logging must not kill a run, but the audit log can be silently
  incomplete. Fix: a run-scoped `logging_degraded` flag surfaced in
  `terminal.json`.

**Severity:** MEDIUM.

---

### W-9 — Sentinel / heartbeat separation

**Not a current defect.** Sentinels are written non-atomically (`:814-816`,
`llmoses_watcher.py:406-408`) and contain a timestamp nothing reads. Only
*existence* is checked, so atomicity is irrelevant.

**The risk is introduced by W-3/W-27.** Once a liveness signal carries content
that is read, a reader can observe a created-but-unwritten file, parse it empty,
and declare the supervisor dead.

**Resolution.** Sentinel stays edge-triggered, write-once, existence-only — do
**not** append heartbeat timestamps to it. Heartbeat is a separate,
level-triggered file written via tmp + `os.replace`.

**Severity:** LOW now, MEDIUM once W-27 lands.

---

### W-24 — Responder ownership lock

Nothing prevents a watcher and an agent from both responding to the same run
directory, producing nondeterministic guidance. `CONTROL/responder` declares mode
and owner at run start, checked before responding.

**Severity:** MEDIUM.

---

## 3. Agent-orchestrated path (primary)

### W-21 — Trace tooling

**Requirement.** The agent writes its own `AgentTrace` per generation through a
provided tool suite, rather than composing JSON ad hoc. Tools cover: trace
writing, response assembly, and the `CONTROL/abort` signal (W-20).

**Human review is served by two independent channels**, and they should not be
conflated:

- the agent's own session — reasoning loops are expandable in the human
  interface, so the deliberation is reviewable directly
- the run directory — `bias_applied` rows, lever counts, state extractions,
  `run_verdict`, all written by `state_builder.py`, deterministic and unforgeable
  by the agent

The second is the audit trail of record. The first is context. A tool-written
trace sits between them and should be labelled as agent-authored, not presented
as captured output.

**Severity:** HIGH.

---

### W-22 — Context strategy as an experimental variable

**Issue.** Fifty generations of state documents will not fit one agent context,
and degradation is silent: the agent begins summarising, loses earlier
generations, and estimates drift for reasons invisible in the output.

**This is not resolved by architecture.** Discarding cross-generation continuity
to fit a context budget would remove the contribution being studied. Context
strategy is therefore a **variable to ablate**, not a constraint to design
around.

**Requirement.** Do not hardcode a strategy. Make it selectable, record which was
used in run metadata, and instrument its effects. Candidate strategies for
ablation: full history; rolling summary written to disk; per-generation
sub-agents with bounded context; retrieval over the run directory. The existing
per-generation layout (`state/run-N/step-G.json`) already supports all of them.

**Instrument regardless of strategy:** context size at each generation, whether
compression occurred, and what was dropped — otherwise drift is unattributable.

**Severity:** HIGH.

---

### W-23 — Confabulation statistics

**Framing.** For academic research, hallucination *rate* is a finding, not merely
a fault. Detectable-and-recorded is the default; detectable-and-fatal applies
only to cascading failure that makes a run unusable — and even then the crash
statistics are part of the experimental result.

| Metric | Detection | Status |
|---|---|---|
| unknown `program_id`s | not in this generation's state | **W-26** |
| unknown atoms | outside `atom_alphabet` | caught by validator |
| slot coverage | valued / offered | derivable |
| out-of-domain values | `assemble` raises | caught |
| schema failures | validator | caught, not counted |

**Reuse.** `live_agent_verify.py` already hard-fails post-hoc on unknown ids and
missing lever coverage. The detection logic exists; it needs to become a per-run
statistic rather than only an audit-time assertion.

**Fatal thresholds.** Consecutive schema failures, or hallucination causing
missing/fabricated utilities across successive generations.

**Severity:** HIGH. **Depends on:** W-15, W-26.

---

### W-27 — Supervision layer

**Issue.** An agent cannot detect its own wedging. With a human present this is
covered; in unattended or parallel-sweep execution it is not, and a wedged
session blocks MOSES indefinitely while appearing healthy.

**Requirement.** An outer supervisor that:

- detects a wedged or dead agent session and triggers `CONTROL/abort` (W-20)
- for parallel sweeps, monitors N concurrent sessions and reports per-session
  verdicts
- is itself dumb and observable — it must not be the component whose liveness is
  in question

**This replaces the robustness the unattended watcher was carrying.** It is the
one genuinely new obligation created by making the agent primary, and the reason
the reduction of W-13/W-14/W-16/W-3 is a net simplification rather than a
deletion of necessary safety.

**Severity:** HIGH.

---

### W-28 — Protocol versioning

**Issue.** In the agent-orchestrated path, the skill *is* the experimental
protocol. Undeclared drift in it between runs silently invalidates comparisons,
exactly as an undeclared prompt change would.

**Requirement.** Skill, tool definitions, and sub-agent architecture are versioned
and pinned per experiment, with the identifier recorded in run metadata and
surfaced in `terminal.json`. Ablation across skill and tool architectures is a
planned experimental dimension, which makes the version the axis label — without
it the ablation is unattributable.

**Severity:** HIGH.

---

### W-25 — Per-platform agent configurations

Codex and Claude Code differ in retry behaviour (Codex performs five internal
network reconnects, as measured), trace exposure, sub-agent support, and config
format (`AGENTS.md` vs `CLAUDE.md`). Build one at a time; do not abstract over
them prematurely.

**Severity:** MEDIUM. **Depends on:** W-21.

---

## 4. Bounded estimator path (option and baseline)

Reduced in scope from the withdrawn Mode A. The estimator **reports**; the
supervisor **decides**.

### W-13 — Provider error reporting

**Issue.** `estimate()` has exactly one error class. `live_estimator.py:301`
catches `KeyError, ValueError, AssertionError, RuntimeError` in a single handler,
and `_run_provider` raises `RuntimeError` for every provider failure regardless
of cause (`:181`, `:199`). Network drop, expired key, **quota exhaustion**, rate
limit, moderation refusal, malformed JSON, and schema violation are all retried
twice. No mechanism exists to express "do not retry this".

**Resolution — adapter.** Classification cannot come from `codex exec` exit
codes, which we do not control. But `LLMOSES_LIVE_CMD` (`:172-183`) already
exists as a provider seam. Own a thin adapter that invokes the provider and emits
a structured error document (`class`, `code`, `retryable`, `detail`). No provider
modification, therefore no breaking-change risk. Move the direct `codex exec`
invocation (`:185-203`) *into* the adapter so there is one provider path rather
than two with different error fidelity.

**Verified signatures (probe Part E):**

| Class | Exit | Signature |
|---|---|---|
| Auth | 1 | `401 Unauthorized`, `invalid_api_key` |
| Network | 1 | `Reconnecting... N/5` then `stream disconnected before completion` on `/codex/responses` |
| Quota / 429 | — | **not characterised — fails safe** |

**Match against the whole of stderr, not a prefix** — the first ~500 characters
are plugin-cache and interface warnings; the diagnostic error is at the tail.

**Unknown class defaults to non-retryable + report**, so incomplete knowledge
fails safe.

**Scope reduction.** This item is now about *accurate reporting upward*. The
decision of what to do about a classified failure belongs to the supervisor.

**Severity:** MEDIUM (was HIGH).

---

### W-14 — Retry budget

**Retry budget is one, and retry is diagnostic rather than therapeutic.** Retry
is justified only where the operation should have succeeded first time, so a
second failure indicates a defect rather than variance — the joint probability of
two independent transient failures is negligible. The system must not
stochastically beat errors out of its own mechanisms.

| Class | Retry | On failure |
|---|---|---|
| Network | **none** — provider already retries 5× internally | report |
| Auth | none | report |
| Quota / credit | none | report |
| Rate limit (429) | 1, with backoff | report |
| Provider timeout | 1 | report |
| Moderation / refusal | none (deterministic) | report |
| Malformed output | 1 | report |
| Schema / slot violation | 1 (error fed back) | report |

**Network is non-retryable at our layer** because the probe showed `codex exec`
already performs five internal reconnect attempts before failing (32.7 s wall). A
retry at our layer is attempt six through ten — precisely the pseudo-infinite
retry to be avoided.

**Rate limit and quota must not be collapsed:** the first is transient, the
second terminal.

**A retry that succeeds is still an anomaly and must be recorded** — something
that should have worked didn't. Retry counts feed the `degraded` verdict.

**Scope reduction.** The consecutive-generation escalation ladder is withdrawn;
that decision now belongs to the supervisor, which has better information.

**Severity:** MEDIUM (was HIGH). **Depends on:** W-13.

---

### W-16 — Timeout invariant (conditional)

**Issue.** Stock defaults are mutually inconsistent:

| Setting | Default | Source |
|---|---|---|
| `LLMOSES_LIVE_TIMEOUT_S` | 240 s per attempt | `live_estimator.py:21` |
| `LLMOSES_LIVE_RETRIES` | 2 → 3 attempts | `:22` |
| Estimator worst case | **720 s** | derived |
| `LLMOSES_RESPONSE_TIMEOUT_S` | **30 s** | `state_builder.py:120` |

MOSES abandons at 30 s, applies stale guidance, and never reads the eventual
response. It works only because `live_agent_demo.sh:96` hand-sets `900` — a magic
number encoding an unenforced invariant. `lambda_sweep_demo.sh:83` and
`utility_policy_test.sh:143` use 30 s, correct for mock modes and silently wrong
under live.

**Resolution.** Assert at startup that
`LIVE_TIMEOUT_S × (RETRIES+1) < RESPONSE_TIMEOUT_S`; fail fast.

**Now conditional.** The conflict exists only when the bounded estimator is in
use. In the agent-orchestrated path there is no competing provider deadline, and
`RESPONSE_TIMEOUT_S` becomes a generous backstop behind W-20 and W-27 rather than
the primary bound.

**Calibration.** `trace["wall_time_s"]` is already recorded per attempt
(`:268, 292`), so runs under `llmoses/outputs/live-demo/*/traces/` already contain
a duration distribution. Use its tail plus margin. The 16.2 s probe observation
was *medium* effort at 184 reasoning tokens — light.

**Severity:** MEDIUM (was HIGH).

---

### W-3 — Heartbeat

**Reduced job.** In the agent-orchestrated path the agent holds the MOSES process
handle and detects its death directly. The heartbeat's remaining purpose is the
*reverse* direction — letting MOSES distinguish a live-but-busy supervisor from a
dead one, which matters because MOSES runs in a container while the supervisor
runs on the host, so OS-level parent-death detection is unavailable.

| Observation | Meaning | Action |
|---|---|---|
| response sentinel appears | success | proceed |
| counter advancing, no sentinel | supervisor alive, work outstanding | wait to backstop |
| counter static | supervisor dead | abort, non-zero |

**Use a monotonic counter, not wall-clock deltas.** Supervisor and MOSES sit on
opposite sides of the container boundary in different clock domains, and Docker
Desktop VM clock drift after host sleep is a known problem; wall-clock liveness
would produce phantom aborts after every lid close. The reader asserts the
counter *advanced*, which is clock-free.

**Cannot prove the estimator is alive** — reasoning is silent (§5). It
distinguishes supervisor-dead from supervisor-busy only.

**Severity:** MEDIUM (was HIGH). **Depends on:** W-9.

---

### W-18 — Salvage as a recorded outcome

Two independent salvage layers — `live_estimator._salvage_values` (`:221-251`)
and `llmoses_watcher.py:320-337` — drop entries until the document validates. A
response salvaged from 40 slots to 2 still returns as a **non-decline**,
indistinguishable at ingest from a complete response.
`HANDOFF-milestone2-followups.md:107-118` raises the same concern for replay.

**Resolution.** Record a degradation measure (slots requested vs. survived) as a
first-class outcome feeding W-19, in both layers.

**Severity:** MEDIUM.

---

## 5. Timing — settled by probe

`codex exec` is *not* pipe-buffered, but model reasoning is silent. On a real
17,073-character rendered LLMOSES strategy prompt (62 slots, `coverage=full`,
gpt-5.5, medium effort): startup chunks at 0.35–0.98 s, `thread.started` at
1.132 s, `turn.started` at 1.145 s, then **16.232 s of silence**, then
`item.completed` with the whole 2,007-character answer at 17.377 s.

Decisively: `reasoning_output_tokens: 184` with `reasoning_event_count: 0`.
Reasoning occurred and emitted no events. `--json` provides no dependable
reasoning heartbeat.

**Consequences:**

- **Idle-timeout-on-output is not viable** — the silent window is the entire
  working duration, so a healthy reasoning agent and a wedged one are
  indistinguishable while it lasts.
- **A wall-clock backstop stays** (W-16, W-27).
- **JSONL is still worth adopting** for structured completion, usage accounting,
  error classification, and tool-call loop detection.
- **Token caps are unavailable in-call** — usage arrives only at
  `turn.completed`, so it is post-hoc accounting, not a runaway guard.

**Implementation trap.** With a prompt argument supplied while stdin remains
open, the CLI prints `Reading additional input from stdin...` and waits for EOF.
The current `subprocess.run(input=...)` handles this; a move to `Popen` must
explicitly close stdin.

---

## 6. Work items

| ID | Item | Path | Severity | Depends on |
|---|---|---|---|---|
| W-2 | Generation fence (subsumes W-1, W-1b) | shared | HIGH | — |
| W-5 | Response status taxonomy | shared | HIGH | — |
| W-26 | Fabricated `program_id` detection | shared | HIGH | — |
| W-20 | Abort channel | shared | HIGH | — |
| W-15 | Failures reach `capture_failures` | shared | HIGH | W-5 |
| W-19 | `run_verdict` in `terminal.json` | shared | HIGH | W-15 |
| W-21 | Trace tooling | agent | HIGH | W-5 |
| W-22 | Context strategy as variable | agent | HIGH | — |
| W-23 | Confabulation statistics | agent | HIGH | W-15, W-26 |
| W-27 | Supervision layer | agent | HIGH | W-20 |
| W-28 | Protocol versioning | agent | HIGH | — |
| W-13 | Provider error reporting (adapter) | estimator | MEDIUM | — |
| W-14 | Retry budget | estimator | MEDIUM | W-13 |
| W-16 | Timeout invariant (conditional) | estimator | MEDIUM | — |
| W-3 | Heartbeat | estimator/shared | MEDIUM | W-9 |
| W-18 | Salvage as recorded outcome | estimator | MEDIUM | W-5 |
| W-17 | M1 logging gaps | shared | MEDIUM | — |
| W-24 | Responder ownership lock | shared | MEDIUM | — |
| W-25 | Per-platform agent configs | agent | MEDIUM | W-21 |
| W-9 | Sentinel / heartbeat separation | shared | LOW→MED | — |
| W-10 | `fsync` durability (flag, default off) | shared | LOW | — |

### Suggested order

1. **W-26** — no dependencies, no behaviour change; starts generating
   hallucination-rate data immediately
2. **W-5** — the contract; everything downstream builds on it
3. **W-2** — keystone correctness fix
4. **W-20** — enabler; all escalation is inert without it
5. **W-15 → W-19** — make failure visible in the deliverable
6. **W-21 → W-27 → W-28 → W-22 → W-23** — the primary path
7. **W-13 → W-14 → W-16, W-3 + W-9** — bounded estimator
8. **W-17, W-18, W-24, W-25**, then optional **W-10**

**Two bands within M2.** Everything is M2, but items divide by what they block:

- **Blocks experimentation** — the harness cannot be trusted to run: W-2, W-5,
  W-20, W-27, W-21.
- **Blocks publication** — runs execute but results are not interpretable:
  W-19, W-15, W-26, W-23, W-28, W-22.

Both must land before M3. The distinction matters only under schedule pressure: a
harness that runs but cannot be interpreted is recoverable; results from a
harness that was silently broken are not.

---

## 7. Decisions — closed

1. **Moderation → abort.** Not because it is our fault but because it is not
   survivable. Generalised into §1.3.
2. **Retry budget = 1.** No stochastic error-beating.
3. **Uniform behaviour; no demo/experiment split.** Run-level degradation is
   abolished (§1.3); experiment-level `degraded` applies uniformly. The replay
   flag in `HANDOFF-milestone2-followups.md:112-125` is shared but is **not** a
   strict/lenient toggle — it encodes a different *requirement*: replay needs
   bit-identical guidance for paired comparison, so any salvage drop invalidates
   it, whereas a live run may proceed on partial guidance and record `degraded`.
4. **Agent-orchestrated is primary; the bounded estimator is an option and
   baseline.** Sweeps run parallel agent sessions, which may invoke the bounded
   estimator when an attributable treatment is wanted.
5. **Stochasticity is not an objection.** MOSES is already a seeded stochastic
   search; an agentic estimator adds another stochastic component to a system
   that has them by design. Experimental control comes from lever dropout, state
   dropout, and ablation across skill / tool / sub-agent architectures (W-28) —
   not from making the estimator deterministic.

---

## 8. Verification

Method carries forward from M1 — run the full suite of MOSES demo problems plus
hard edge cases, requiring every step of every run to complete with **complete
extraction**: every target parameter present in the intermediary state for every
generation.

M2 adds three requirements:

**A. Complete utility surface.** Every generation of every demo receives a
response; every response validates against the schema; every lever is exercised
across the suite; slot coverage reported per run. No gaps, no silent timeouts.

**B. The existing battery still passes.** The 50-assertion battery (TRANSPORT 9 +
POLICY 41, plus native smoke suites) must pass unchanged. This is what the additive
`status` field protects — any change requiring edits to the battery to stay green
is a design smell and should be re-examined before proceeding.

**C. Failure injection — new, and the substantive addition.** M1 verified that
success paths succeed. M2's thesis is that *failures behave correctly*, which
cannot be verified by running happy paths.

| Injected | Expected |
|---|---|
| Invalid credential | classified auth, no retry, reported, run aborted, verdict `aborted` |
| Network unreachable | classified network, no retry at our layer, abort |
| Malformed provider output | one retry, then report; both attempts logged |
| Fabricated `program_id` | run continues, counted, verdict `degraded` (W-26) |
| Supervisor killed mid-run | heartbeat stalls, abort, distinguishable from timeout (W-3) |
| Response never written | abort — **not** silent native continuation (§1.3) |
| Deliberate `204` abstention | run continues, verdict `ok`, not counted as failure |
| Agent session wedged | supervisor detects, triggers abort (W-27) |

Each assertion must reverse-check: it has to fail against pre-change code. A test
that passes on today's codebase is testing nothing, since today's codebase
silently swallows every one of these.

**Done criteria per item:** behaviour asserted by at least one injection test,
the 50-assertion battery unchanged and green, and `terminal.json` carrying the
correct verdict.

---

## 9. Closed

**W-11 — inotify rejected.** The run directory is a bind mount and the blocking
side runs inside the container; host→container inotify propagation across
virtiofs / gRPC-FUSE is unreliable. Latency is not a concern for an experimental
harness. `IN_Q_OVERFLOW` also means any correct push design must retain a
reconciliation scan, so push can never be the correctness mechanism. Polling is
retained deliberately.

**Hook re-entry hypothesis — dead for the tested seam.** Probe showed exactly one
`flush_gen` and one `await_response` per generation across three configurations,
with no correlation to `nDeme` or candidate count. Neither the blocking response
nor its timeout return triggers PeTTa goal retry. `_cratio_applied_for` is
confirmed consistent with protection against documented cumulative compounding.
Residual untested scope (multi-deme materialisation, strategy problem type) is
**absorbed by W-2**, which makes re-entry harmless by construction.

**Idle timeout on provider output — rejected.** See §5.

**Provider interface — resolved** to the adapter approach (W-13); no provider
modification required, seam already exists.

**Two-mode split — withdrawn.** See §1.4.

---

## 10. Deferred / out of scope

**Deme capture fidelity (M1, not M2).** The re-entry probe fixture requested
`nDeme=2` but captured 1 deme in all three generations, including generation 3
where 2 exemplar candidates were present
(`llmoses/llmoses-tests/boolean_state_test.metta:125`). This may be correct —
`nDeme` is a target and deme creation depends on selection — but captured deme
count feeds the state document the responder consumes, so a discrepancy would be
a capture-fidelity issue. Confirm separately.

**W-12 — direct-dispatch test path.** Polling round-trip (~75 ms/generation) is
negligible in production and dominant in the test battery. A direct in-process
dispatch mode would remove IPC from the test path, but that path would no longer
exercise the transport, so at least one transport-level integration test must be
retained. Optional.
