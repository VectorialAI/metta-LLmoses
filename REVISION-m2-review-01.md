# M2 Hardening — Revision 01 (post-review)

Four changes against the landed tree. Companion to `PLAN-m2-hardening.md`;
amends it where noted.

---

## R1 — Move the abort expectation off `CONTROL/responder`

**Current.** Abort-on-missing-response is gated on `CONTROL/responder` existing.
No declared responder → run degrades to native, clears the buffer, records a
quality flag, exits zero.

**Problem.** Failure detection depends on an artifact the failing component was
responsible for creating. An agent that crashes before declaring itself produces
a complete native run that exits zero — the silent-success outcome §1.3 exists to
abolish, and in a sweep it looks like data. The more broken the responder, the
less likely an abort. This violates a principle the plan already states for the
heartbeat: liveness must not be signalled by the component whose liveness is in
question.

**Change.** The *run configuration* declares the expectation, not the responder.
The driver controls it and a crashing responder cannot suppress it.

- `LLMOSES_AWAIT_RESPONSE=1` means an estimate is expected. Absence of any
  responder is then a **failure**, not a licence to degrade.
- `CONTROL/responder` keeps its W-24 job — preventing two responders racing — and
  stops doing a job it cannot do reliably.

**Interlock-window ablations.** The expectation must be a *generation predicate*,
not a boolean, because frontloaded and backloaded reasoning interlocks are
planned ablations: the agent estimates for a subset of generations and MOSES runs
native outside that window. Absence of a response outside the declared window is
expected and must not abort.

Suggested shape: an explicit expected-generation spec (`all` by default; a range
or list otherwise), recorded in run metadata so the window is visible in
`terminal.json` alongside the verdict. Anything outside the window is native by
design and reported as such, not as degradation.

**Battery.** The TRANSPORT "responder suppressed" phase asserts the old
degrade-to-native contract and must be **edited** — it now asserts behaviour the
plan deliberately changed. If that scenario is still worth covering, it gets an
explicit "no responder expected" configuration rather than being inferred from a
missing file.

**Plan amendment.** §8.B ("battery must pass unchanged; any edit is a design
smell") is too broad and is what forced the gating workaround. Amend to: *tests
asserting behaviour this plan deliberately changes are expected to be edited, and
the edit must be called out in the report. Every other edit remains a design
smell.*

**Acceptance.**

- injection: responder never declares → non-zero exit, verdict `aborted`
- injection: responder declares then dies → non-zero exit (unchanged)
- frontload and backload window configs run to completion without abort, with the
  window recorded in `terminal.json`
- the edited TRANSPORT phase is listed explicitly in the report

---

## R2 — Split W-26 into two buckets

**Current.** Ids are validated against everything that existed in generation *G*
(pre-merge members ∪ new entrants ∪ survivors) and counted as one rate.

**Why split.** The responder is *offered* the survivor set
(`_survivor_scores` restricts to `resize_cull.survivors`; `build_slots` builds
from that), but is *shown* more than it is offered — the evidence digest renders
`top_metapopulation` from the pre-merge `members` list. So two different
phenomena are currently collapsed:

| Bucket | Meaning | Signal |
|---|---|---|
| **A — fabricated** | id existed nowhere in generation *G* | hallucination rate |
| **B — unoffered** | id existed in *G* but was not in the offered slot set (e.g. culled at merge) | protocol-adherence rate |

Anything in the offered set is simply correct.

Bucket B is not hallucination — the model genuinely saw the id — it is the model
ignoring the slot constraint. Reporting them as one number makes the headline
research metric noisier than it needs to be, and the two imply different
remedies: A points at grounding, B points at constraining the state space
presented to the model.

**Change.** Record both as separate per-channel rates
(`unknown_ids` / `unoffered_ids`, each over `total_ids_supplied`), across all
three id-bearing channels. Both sets are already available at ingest; no extra
I/O.

**Acceptance.**

- an id absent from generation *G* entirely lands in A
- an id present pre-merge but culled at merge lands in B, not A
- an offered id is counted in neither
- both rates surface in `terminal.json` and feed the `degraded` verdict

---

## R3 — Session token: confirm and constrain

**No change to the mechanism.** The session token is correct and the PID
approach the review rejected would have been broken by design — an agent is not
one process, and W-22 explicitly plans per-generation sub-agents, so the writing
process routinely differs from the claiming one. This affects a *single* run with
sub-agents, not only parallel swarms. There was no prior ownership mechanism of
any kind; W-24 is new, so nothing legacy constrains it.

**Two constraints to add.**

1. **Mint per run.** A token from a previous run must not be able to claim a new
   one. Regenerate at claim time; reject a token whose run identity does not
   match.
2. **Document what it is not.** It is a coordination mechanism, not an
   authorization boundary — anything with filesystem access can read it. It
   prevents accidental doubling, dropping, or cross-over of responses between
   concurrent sub-processes. It is not a security control and should not be
   described as one.

**Acceptance.**

- a sub-process presenting the token responds successfully (different pid from
  the claimer)
- a stale token from a prior run is rejected
- two claimants against one run directory: second is refused

---

## R4 — Flush before `os._exit`

**Current.** Abort uses `os._exit(3)`, which is the right call from inside the
Prolog-embedded context — raising would propagate into the Prolog goal, which the
existing docstrings forbid.

**Problem.** `os._exit` skips all cleanup: no `atexit`, no buffer flushing. The
abort path therefore risks losing its final log rows — precisely the evidence
explaining why the run aborted.

**Change.** Before `os._exit`, explicitly:

- flush and `fsync` the native log handle `_NFH`
- confirm `terminal.json` is fully written, flushed, and its `os.replace`
  completed — not merely staged from a still-buffered temp

**Acceptance.** An abort-path injection test asserts that, after the non-zero
exit, `moses_native_log.jsonl` contains the abort row and every row preceding it,
and `terminal.json` parses with the correct verdict.

---

## Order

R4 and R3 are independent and small. R2 is independent. R1 is the only one
touching the battery and should land last, with its test edits itemised in the
report.
