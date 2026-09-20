# HANDOFF — Milestone II submission follow-ups

Origin: Cowork session, 2026-07-28. Author: Claude (planning/reasoning owner).
Target: Claude Code session on the host, with `codex-delegate` MCP available
(Sol 5.6 high as senior collaborator; experiments driven by gpt-5.5 medium).

This document is the contract. It carries the design decisions already made, so
the receiving session should not re-derive them — it should challenge them if
they are wrong, then implement.

---

## Why this exists

The Milestone II submission draft (`LLMOSES-Milestone-II-Submission.docx`,
produced in the originating session) describes a λ = 0 / 0.5 / 1.0
demonstration across the three live demos. That artifact does not exist yet.
What exists today:

| Artifact | λ coverage | Estimator | Location |
|---|---|---|---|
| Live agent demos (bool-std, bool-cull, bool-cull-r4, strategy) | 1.0 only | gpt-5.5 **medium**, coverage=full | `llmoses/outputs/live-demo/` |
| λ sweep (atom_pair, synergy_pair) | 0 / 0.25 / 0.5 / 0.75 / 1.0 | deterministic **mock**, not an agent | `llmoses/outputs/lambda-sweep/` |

So the only genuine λ triple is mock-driven and covers the atom-prior lever
alone. There is no agent-in-the-loop triple. That is gap #1.

Gap #2: `llmoses/readme.md` documents Milestone I only. It has no mention of
the apply-lever switch plane, λ, the live estimator, or how to reproduce any
M2 result. The submission points SingularityNET at that file.

`LLMOSES_LIVE_MODEL` / `LLMOSES_LIVE_EFFORT` are never set by
`live_agent_demo.sh:81-104`, so the stored runs are the defaults (gpt-5.5,
medium). **Medium is confirmed fine — do not redo the existing runs for model
reasons.** They remain valid as the full-walk realism evidence.

---

## Design decision: constrained replay (settled — implement, don't relitigate)

The naive triple is to run each demo three times with a live agent at λ ∈
{0, 0.5, 1.0}. That confounds λ with agent nondeterminism: three independent
response sets, three different behaviors, no way to attribute the delta to the
dial.

The fix is to hold the response fixed and vary only λ. But **replay is only
valid for the first meta-loop iteration.** After generation 1 the cells diverge
structurally — different exemplar selected, different merges, different
survivors — and `program_id` is a hash of the full raw tree (D-PID). A response
captured in the λ=1 cell at generation 3 references programs that do not exist
in the λ=0 cell's generation 3. It would ingest, match nothing, and degrade to
"missing = neutral" across the board: a cell that appears to run but proves
nothing.

**Therefore: constrain every replay walk to 2 generations.**

- Generation 1 state is identical across all three cells (fixed
  `LLMOSES_RNG_SEED`, identical seed metapopulation, no guidance applied yet).
- The generation-1 response is captured **once** per (demo, seed) from a live
  agent, then replayed byte-identical into all three λ cells.
- A response to generation G applies to generation G+1's draws, so the gen-1
  response gets exactly one round of application at generation 2 — where all
  five apply-levers fire (exemplar selection, culling, comparator re-sort,
  complexity ratio, atom prior).
- Generation 2's own response would apply to a generation 3 that does not
  exist, so post-gen-2 divergence is out of scope by construction.

This is a clean isolation of the dial. It is also *narrow*, and the submission
must say so — see "Report obligations" below.

### The independent-run experiment is not replaced, it is documented

SingularityNET must be able to run both:

1. **The constrained replay triple** — reproduces our stated numbers exactly.
2. **An independent live-call experiment across the full example set** — fresh
   agent calls every generation, full-length walks, no replay. This is how the
   system actually operates in practice; the existing `live-demo/` runs are
   instances of it at λ=1.

Both procedures go in the readme with runnable commands. Do not ship a readme
that only supports the constrained case — that would misrepresent the system as
being a two-generation toy.

---

## Work item 1 — `replay` watcher mode

New value for `LLMOSES_MOCK_UTILITY_MODE`: `replay`, parameterised by
`LLMOSES_REPLAY_DIR` (path to a stored `utilities/` tree, or to a single
captured run root).

Dispatch slots in at `llmoses/utilities/llmoses_watcher.py:298-303`, alongside
the existing `live` / mock branches. It reads
`<LLMOSES_REPLAY_DIR>/utilities/run-<seq>/step-<gen>.json` and returns that
document verbatim.

### Failure semantics — this is the part that needs care

The surrounding code is built for a live agent and is *deliberately* forgiving.
Both behaviours are wrong for replay:

- **`llmoses_watcher.py:304-307`** — a bare `except Exception` turns any
  estimator failure into a neutral decline with only a stderr line. Under
  replay, a missing or unreadable file would silently produce a cell that
  ingests nothing, applies nothing, and *looks* like a completed run.
- **`llmoses_watcher.py:320-337`** — an invalid document is salvaged
  component-by-component and written with whatever survived. A partially
  salvaged replay is a corrupted paired comparison: the cells would no longer
  be receiving the same guidance.

Replay must therefore **hard-fail, loudly, and abort the run** on:

- missing replay file for the requested `run-<seq>/step-<gen>`
- unreadable / unparseable JSON
- validator rejection against the *current* run's `atom_alphabet`
- any salvage drop whatsoever (drops are failures here, not repairs)

Implement this by branching before the forgiving paths rather than by loosening
them — the live path's tolerance is load-bearing and must not regress. Suggested
shape: replay sets a `strict` flag; the `except` and salvage blocks re-raise
when it is set; `main()` exits non-zero and the driver treats a dead watcher as
a failed run (`LLMOSES_RESPONSE_TIMEOUT_S` will otherwise mask it as a timeout
— check that the timeout path is distinguishable in `terminal.json`'s
`capture_failures`).

### Premise verification (do not skip)

The replay design rests on "generation-1 state is identical across cells." That
is an assumption about determinism, not a proven fact. Before trusting any
triple, assert it:

- the replayed response's `program_id` values are a **subset** of the target
  run's generation-1 candidate ids (from `action/run-N/step-1.json`)
- the target run's `run_config.json.atom_alphabet` is **identical** to the
  capture run's
- the generation-1 `state/run-N/step-1.json` metapopulation member ids match
  the capture run's

If any of these fail, the premise is broken and the experiment is invalid —
report it rather than working around it. This is the single most likely way the
whole design quietly fails.

---

## Work item 2 — λ-parameterised demo runner

`llmoses/llmoses-tests/live_agent_demo.sh` hardcodes λ=1 for all five levers,
`LLMOSES_RNG_SEED=101`, and full-length walks
(`live_agent_demo.sh:98-105`). It needs to support the matrix without
regressing its current single-shot behaviour, which the stored `live-demo/`
runs depend on for reproducibility.

Preferred shape: a **new** script (`llmoses/llmoses-tests/lambda_triple_demo.sh`)
rather than overloading the existing one — the existing script is referenced by
the M2 design spec §5.2.1b and by the stored artifacts, and its current
behaviour should stay byte-stable. Reuse, do not copy-paste, the docker
invocation and watcher lifecycle: if that means extracting a shared helper both
scripts source, do that, and make **both** call sites use it (no mixing the
helper with an inlined duplicate of what it wraps).

Requirements:

- usage: `lambda_triple_demo.sh <demo> <lambda-list> <seed-list> <outdir>`
- `demo ∈ {bool-std, bool-cull, strategy}`; drivers constrained to **2
  generations** (bool-std and strategy need their generation counts overridden
  from the existing drivers; bool-cull's `runMoses 4 ...` first argument is the
  generation count)
- per (demo, seed): one live capture pass at λ=1 with
  `LLMOSES_MOCK_UTILITY_MODE=live`, `LLMOSES_LIVE_COVERAGE=full`, model/effort
  left at defaults (gpt-5.5 / medium)
- then one replay pass per λ in the list, `LLMOSES_REPLAY_DIR` pointed at the
  capture run
- λ applies uniformly to all five `LLMOSES_LEVER_WEIGHT_*` vars
- **λ=1.0 cell**: reuse the capture run itself. Re-running it under replay is
  redundant and risks a spurious mismatch; if you do re-run it for uniformity,
  assert the two agree.
- every cell writes its run root under `<outdir>/<demo>/seed-<s>/lambda-<λ>/`

### Strategy-path caveats (read before wiring a strategy sweep cell)

`lambda_sweep_demo.sh` wires exactly two drivers, `std` and `cull`, both
parity3. **The entire seeded calibration is boolean-path.** The width-3 branch
at `lambda_sweep_demo.sh:374` shows the reporting code is width-aware, but no
strategy driver is attached.

If a strategy sweep cell is added, the expected-share theory must be rederived —
**do not port the boolean formula.** `1/(1+2(1−λ))` follows from the boolean
pool composition (2 chosen of P(3,2)=6 ordered pairs at arity 3). Strategy draws
width-3 triplets from P(5,3)=60 with a different chosen-set size, so the
expected value is a different quantity. A cell run against the boolean theory
will fail its containment verdict for the wrong reason, and — worse — could pass
for the wrong reason.

Separately: the strategy demo runs without population pressure (metapop 6 → 6,
no resize), so **resize culling and dominated-candidate escape never fire on the
strategy path** — in the existing live run, in the constrained triple, or in any
strategy sweep. Those two levers are boolean-path-only in evidence terms. Either
build a pressure-bearing strategy driver (mirroring what `cull` does for
boolean) or state the limitation; do not let a verdict imply coverage that does
not exist.

For reference, the stored strategy live run
(`llmoses/outputs/live-demo/strategy/`, 3 generations, nDeme=2) shows 3
`utility_ingest`, 11 `bias_applied` (atom_prior 8, exemplar_selection 2,
complexity_ratio 1), 40 `combo_pick` rows, and `comparator_overrides` 0/11/15 —
with `contextual: true` and `synergy: true` on every atom_prior row.

### Cost note

Replay makes reps nearly free — the provider is called once per (demo, seed),
not once per cell. 3 demos × 5 seeds × 3 λ = 45 runs but only **15 live
calls**, at ~10 s and ~7.5k prompt chars per generation. Start with 3 seeds to
validate the harness end-to-end, then scale. Do not scale before the premise
verification above passes.

---

## Work item 3 — verification and QA

Two distinct things, both required.

**(a) Harness verdicts** — extend or mirror `live_agent_verify.py` for the
triple. Hard-fail (exit non-zero) on:

- λ=0 cell showing **any** `bias_applied` / `combo_pick` / `comparator_overrides`
  row — this is the off-equivalence guarantee and it is load-bearing for M3
- any cell with zero `utility_ingest` rows, or `schema_ok=false`
- any cell whose replayed document differs from the captured document
- premise-verification failures (previous section)
- monotonicity violation in applied-bias counts across λ, per demo

**(b) Independent QA pass** — delegate to a *fresh* Codex context (gpt-5.5,
high reasoning) with repo + artifact access, and no sight of the claims being
checked. Ask it to answer, from artifacts alone: does the λ dial demonstrably
do what the submission says, and is anything overstated? This mirrors the
`sol-review-milestone2.md` review that drove the v20 hardening pass, and that
review found real MAJOR defects — expect this one to as well, and budget time
to fix what it finds rather than filing it.

Do not let the same context that produced the runs also bless them.

### Non-vacuity check

Before believing a green verdict, break something on purpose and confirm the
verdict goes red — e.g. point a λ=0 cell at a λ=1 replay document, or corrupt
one program id in the replayed response. The D-034 mutation-testing precedent
applies: a suite that passes on a broken base tests nothing.

---

## Work item 4 — readme M2 section

`llmoses/readme.md` currently ends at Milestone I. Add a Milestone II section
covering:

- the two switch planes (`LLMOSES_EMIT_LEVERS`, `LLMOSES_APPLY_LEVERS`) and
  per-lever `LLMOSES_LEVER_WEIGHT_<NAME>`, with the default (`APPLY` empty =
  pure shadow) stated explicitly
- `LLMOSES_MOCK_UTILITY_MODE` values, including `live` and the new `replay`
- `LLMOSES_LIVE_MODEL` / `LLMOSES_LIVE_EFFORT` / `LLMOSES_LIVE_COVERAGE`
- `LLMOSES_RNG_SEED` as the experiment control
- **procedure A**: reproduce the constrained replay triple (exact commands,
  expected outputs, where they land)
- **procedure B**: run an independent live-call experiment across the full
  example set at any λ — the practical-operation path, explicitly flagged as
  the one that shows real behaviour
- what each output directory contains and which files matter for review

Write it for a reader who has the repo and Docker and nothing else.

---

## Report obligations (back to the submission doc)

The `.docx` needs edits once results exist. Do not just append numbers:

1. **Sample-data section** currently implies three live settings per demo across
   full walks. Rewrite to describe the constrained 2-generation replay design.
2. **State the rationale explicitly** — that replay isolates λ from agent
   nondeterminism, that it is only valid for the first meta-loop iteration
   because the population diverges structurally afterward, and that the walk is
   constrained to 2 generations for exactly that reason. A reviewer who spots
   the 2-generation limit unaided will read it as a weakness; stated plainly
   with its reason, it reads as method discipline.
3. **Keep both evidence classes distinct**: the constrained triple demonstrates
   the dial; the existing full-walk λ=1 `live-demo/` runs demonstrate real
   operation; the seeded mock sweep supplies the statistics. Do not blur them
   into one claim.
4. **Report where outputs live** so the artifacts can be packaged for
   SingularityNET — full paths, per demo, per seed, per λ.

The submission's existing honesty posture (the "Known gaps" section) is what
earned Milestone I top scores. Preserve it: if the triple shows a weaker effect
than expected, say so.

---

## Division of labour

- **Sol (5.6, high)** — senior collaborator on the replay-mode failure
  semantics and the verification design. Specifically worth arguing about: the
  strict/forgiving split in the watcher, and whether the premise-verification
  assertions are sufficient to catch a silent divergence. Ask for disagreement,
  not confirmation.
- **gpt-5.5 medium** — the in-loop estimator for the capture passes.
- **gpt-5.5 high, fresh context** — the independent QA pass (3b).
- **Claude** — owns the plan, reviews every diff against the six-axis rubric
  (behavioural correctness, regression safety, mechanical cleanliness, test
  correctness, scope discipline, code quality), and writes the final report and
  submission edits.

Scope discipline note: this work touches the watcher, one new script, one
verifier, and the readme. It is not an invitation to refactor `state_builder.py`
or restructure the test tree.
