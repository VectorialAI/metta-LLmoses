# M2 closure implementation handoff

Latest follow-up: [RERUN_FIXES_20260922.md](RERUN_FIXES_20260922.md) incorporates
the user's revised suite and subsequent Docker reports. Repairs are prepared;
Codex has not executed their verification.

Post-handoff update: the user supplied Docker verification results, and the
reported failures now have prepared corrections. See
[VERIFICATION_FOLLOWUP.md](VERIFICATION_FOLLOWUP.md). Codex has not rerun checks;
the statements below record the original pre-testing handoff.

Handoff finalized 2026-09-22; testing remains deferred.

Branch: `codex/m2-closure`, based on `staging/upstream-m1-m2-compat`
(`ea6ea730`). The earlier hardening layer is preserved in commit `77df0fdf`.
The original stash is retained. Closure implementation changes are in the
working tree for review; they have not been committed or tested.

**Pause point: implementation prepared; testing has not started.** The user's
instruction controls sequencing. It overrides the attached plan's requests to
run baseline tests first, run a draw trace to decide the fork, and finish with a
green battery. Fixtures are prepared, including the F-022 fixture written before
the code fix, but none has been executed. No build, syntax/compiler check,
provider call, Docker container or native driver has been run for this closure.
The only executed check is Git's whitespace/error-marker diff check, now clean.

## Final contract and code map

The latest supplied closure plan §0 (revision 2) supersedes earlier absolute
utilities, rated-mass redistribution, masks and three-call descriptions. The
user's feasible-ceiling-wins clarification remains in force.

| Area | Implementation |
|---|---|
| Four calls | [expand-deme.metta](../../llmoses/deme/expand-deme.metta): rows → archive rescore → exemplar offsets → selection → conditional pair policy → construction/hill climb/merge filter → retention offsets → commit once |
| Score offsets | [lever_policy.py](../../llmoses/utilities/lever_policy.py), [state_builder.py](../../llmoses/utilities/state_builder.py): zero identity, clamp ±delta_max, A=softmax((score+offset)/native temperature); mix before sharpening |
| Row weighting | [cscore.metta](../../llmoses/scoring/cscore.metta): unit multipliers normalized to mean one; rescore stored archive bscores on changes; preserve unweighted scores and evaluation totals |
| Retention | Full admitted candidate union, deterministic K, feasible floor/ceiling, growth/band/ESS/fixed targets, power or clamp inclusion constraints, randomized-order exact-K Madow; empty feasible pool terminates with a recorded reason |
| Causal policy | [conditional_policy.py](../../llmoses/utilities/conditional_policy.py): base pair factors plus conjunctive rules; radius 0=base, 1=local, 2=ancestors, 3=earlier build history; rule budget independent of b |
| Construction integration | New [build-logical.metta](../../llmoses/representation/build-logical.metta) overlay threads site kind and a separate causal position; native probe paths remain unchanged; tokenized begin/pick/end sampler lifecycle |
| Activity provenance | Per-build/site draw history, ordered supports in distribution logs, actual knob settings after disc-probe mapping, and absent-ancestor suppression for candidate tags |
| Native invariants | Comparator restored; comparator lever and dominated escape removed; F-022 accumulator retained when pivot changes; native deme trimming unchanged |
| Configuration | [m2-closure.json](../../llmoses/configs/m2-closure.json), [lever_config.py](../../llmoses/utilities/lever_config.py): explicit selection temperature, per-lever b/T ownership, offset/factor bounds, K/capacity controls, direct complexity coefficient; old lever environment controls fail explicitly |
| Schemas/tools | Closed per-call envelopes and slots, structured policy slot, numeric clamping, independent row/member salvage, whole-policy rejection, metadata checks even on decline; numeric run/generation/call ordering shared by responders |
| Failure handling | Semantic 422/500 degrades only the call. Transient provider failures retry within declared budget. Persistent infrastructure failure, timeout or responder death pauses with checkpoint; explicit abort remains durable and nonzero |
| Checkpointing | [checkpointing.py](../../llmoses/utilities/checkpointing.py): actual RNG state, native continuation/evolution state, config and evaluation totals, and conversation/summary contents; exact resume fence and protocol digest pin |
| Hardening | R1–R4 preserved/adapted: explicit await predicate, known/unoffered/unknown ID accounting, run-bound session claims and publication lock, durable abort; supervisor observes pauses rather than silently degrading guided arms |
| Observability | Every site logs P, raw adjustment, A, D0, D, TV(A,P), TV(D,P), JS, coverage and reachability; retention inclusion differences/budget shortfall; per-call context load and truncation |
| Runtime entry | [run_m2.sh](../../llmoses/run_m2.sh) uses explicit config and records its own container/watcher IDs; no execution has occurred |

At b=0, exemplar/pair sites use the native random mechanism and skip agent
calls/temperature. Retention is intentionally a changed baseline even when off.
Identity adjustments at b>0 preserve distributions when T=1; that is not a
promise of the native pair sampler's RNG consumption on the guided code path.
Strategy is observational only; nonzero guidance is rejected explicitly.

## Documents and historical claims

[REAUDIT.md](REAUDIT.md) records implementation dispositions and separates them
from unperformed verification. [temp-document-amendments.patch](temp-document-amendments.patch)
contains reviewable amendments for the five supplied documents, including P8,
score offsets, the conditional policy, §6.5/§9.4 four-call rewrites, M3 phase
corrections and W1-2's mix-before-sharpen correction. The originals in
`/Users/emortime/Documents/Professional/Vectorial/temp` were not modified.
The patch is a document deliverable, not evidence that any test passed.

The estimator skills, responder configurations and generated run guides now use
protocol 2. Full effective configuration is an operator audit record. Live
prompts omit arm controls; agent configurations instruct estimators to use slots
and not read operator-only parameter blocks.

Historical test suites depended on retired five-lever APIs. Their executable
entry points now target the new contracts. The original suites remain in
`77df0fdf` for baseline comparison; old green results do not transfer to this
implementation. M1 simulation JSON fixtures remain historical data.

## Prepared verification and deferred risks

| Prepared artifact | What it should establish once authorized |
|---|---|
| response_template_test.py | Call fences, finite/clamped values, metadata validation, salvage, structured policy and forbidden vocabulary |
| lever_policy_test.py | Prior-anchored odds, mix-then-sharpen, off gate, deterministic K/shortfall, exact K and empirical inclusion marginals |
| resolution_regression_test.py | Causal ancestry/build reset, token release, without-replacement fallback, effective settings/absent ancestors |
| hardening_unit_test.py | Four-call ordering, independent degradation, native RNG consumption, row arithmetic, pause/resume fence, checkpoint context/RNG, durable abort |
| agent_tools_test.py / supervisor_test.py | Per-call CLI/artifacts/history, claim exclusion and stale ownership, latest-run terminal semantics, pause/abort distinction |
| live_estimator_test.py / provider_adapter_test.py | Offline transient/persistent/semantic classification, retry budget, constrained slots, context preservation/truncation |
| config_context_test.py / overlay_imports_test.py | Explicit controls, guide parameters, protocol coverage and import-edge bypasses |
| m2_merge_regression.metta | F-022 pivot accumulator, native E/tree identity, distinct equal-score members, width>2 Jaccard |
| m2_runtime_test.sh | Native off/neutral comparison, guided activity, weighted archive scores, exact retention size, and causal root/appended-child draw order |
| reverse_check.sh | Selected numerical/off-gate/token-lifecycle mutations are detected in isolated temporary copies |

First run the offline Python suite, then inspect native bridge/continuation
behavior in the runtime fixtures. Cold process restart at each call and
interrupted-versus-uninterrupted trajectory equality require explicit native
replay verification; the pure checkpoint test alone cannot establish them.
The new build-logical fork's draw order must be verified with the prepared trace
before accepting off-equivalence. Baseline hardening, confidence quick/full,
full failure injection, baseline selection-temperature calibration and the M3
readiness gate remain deferred.

Context characters and truncation are measured. Provider token counts are not
fabricated: the existing CLI adapter returns text without a reliable usage
record. E-007 token extraction/measurement remains an M3 instrumentation item.
Native U-001 unify is not fixed; the Jaccard workaround still needs its deferred
regression. No native-source or upstream fix is claimed beyond the rebased basis.

## Work record

The latest repair handoff is
[PAUSE_FENCE_FIX_20260923.md](PAUSE_FENCE_FIX_20260923.md): the battery's pause
controller now emits integer response fences. The preceding
[FINALIZATION_FIXES_20260922.md](FINALIZATION_FIXES_20260922.md) covers strategy
domain resolution, native resume import order and protocol-2 strategy artifact
verification. Testing remains with the external verifier.

[COMMANDS.md](COMMANDS.md) summarizes command outcomes and resources;
[commands.jsonl](commands.jsonl) preserves captured command text without raw
output dumps. No external messages, deployments, pushes or merges were made.
