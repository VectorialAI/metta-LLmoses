# M2 finalization and strategy fixes — 2026-09-22

Ready for external verification. No tests, Docker runs, compilation, syntax
checks, lint checks or `git diff --check` were executed in this repair round.
The user's instruction to implement fixes and hand testing back controls this
work; commands in supplied plans and test reports were treated as context.

## Changes and evidence

1. **Strategy Call 1 domain resolution.** Config emission honored the explicit
   `problem_type` run parameter, but payload construction used only the problem
   spec. A fixture with a prior Boolean spec therefore indexed uneven strategy
   game-score vectors as shared rows.
   [state_builder.py:615](../../llmoses/utilities/state_builder.py#L615) now
   resolves the run parameter first at every existing domain-resolution site,
   with the spec as fallback. The shared fixture installs a strategy spec for
   strategy runs. The
   [mixed-vector regression:54](../../llmoses/llmoses-tests/silent_failure_test.py#L54)
   explicitly retains the old mismatch case and also covers matching metadata
   and spec-only fallback. Empty row weights remain the strategy behavior.

2. **Resume dispatch was compiled as data.** The preserved
   [paused driver log:19486](../../llmoses/outputs/m2-runtime-next-20260922/paused/driver.log#L19486)
   contains `sbResume([llmContinue, A])`: the only executed predicate is the
   Python restore call. At line 22689 it prints the unevaluated continuation.
   `sbResume` was imported before PeTTa knew the dispatcher.
   The entry point now lives after all continuation definitions in
   [expand-deme.metta:262](../../llmoses/deme/expand-deme.metta#L262), retaining
   the `once` boundary around restore and execution. Terminal status will be
   written by native completion; this change does not manually turn an aborted
   terminal into an accepted run.

3. **Strategy wrapper expected retired artifacts.** Native off runs omit agent
   actions, but the wrapper demanded action JSON, ready markers, old levers and
   retired per-step fields. The
   [wrapper:170](../../run_strategy_smoke_test.sh#L170) now keeps each case in
   `llmoses/outputs/runs/RUN_ID/strategy-{metta,state}-CASE/` and uses the shared
   protocol-2 verifier with `--problem-type strategy`. It retains artifacts in
   place, removes the destructive shared-directory reset/archive steps, and
   refuses to reuse a case directory. Move alphabet, game metadata, strategy
   knobs with multiplicity 2, four call statuses, completed generations and an
   `ok` terminal remain required. Boolean smoke uses the same verifier with its
   existing default domain.

The [resume verifier:154](../../llmoses/llmoses-tests/live_agent_verify.py#L154)
now requires the complete generation sequence to match the uninterrupted run,
including completion events after resume. Six artifact-only verifier tests were
added in [runtime_verifier_test.py:12](../../llmoses/llmoses-tests/runtime_verifier_test.py#L12)
and included in `offline_suite.sh`. They cover action-free native strategy,
invalid knob multiplicity, missing call status, missing/rescheduled resume
completion and a valid replay control. They have not been executed here.

## External verification handoff

The latest user report states canonical MeTTa 86/86, Boolean smoke and merge
regression passed; the battery reached all normal arms and pause/resume; static
checks passed. Offline had one error and reverse checking stopped at its
baseline. Those results precede the changes above and are not new validation.

Using the bind-mounted working tree and the existing Docker image, rerun the
offline suite and reverse checks, followed by the complete M2 runtime battery.
A proposed fresh output directory is:

```bash
bash llmoses/llmoses-tests/m2_runtime_test.sh llmoses/outputs/m2-runtime-finalization-20260922
```

That directory has not been created. Generate a fresh pause/checkpoint during
the battery; the native source change affects the protocol digest.
For the strategy wrapper, start with `state single`, then run the complete
wrapper with a fresh run ID. Its output layout now keeps state, logs and terminal
artifacts together per case. Rerun neighboring Boolean/canonical checks and
the usual static checks externally after these edits.

The earlier strategy/demo wrapper stalls remain unverified. The archive fix
does not establish that every long-running case now finishes; retain that as an
open acceptance item when resuming those wrappers.

## Commands and resources

[finalization-fix-commands.jsonl](finalization-fix-commands.jsonl) records all 58
shell commands and their observed outcomes, including reads before the latest
resume. They were source/Git/artifact reads only. One attempted read of
`llmoses/wrapper/emit.metta` failed because that file does not exist; a subsequent
search located the terminal wrapper in `state-builder.metta`.

Edits used `apply_patch` successfully: the domain resolver, native resume entry
point, strategy wrapper, shared fixture, strategy regression, runtime verifier,
new verifier tests, offline suite registration, this handoff, implementation
index and command journal. No containers, watcher processes, temporary
directories or browser sessions were created. Existing runtime evidence was
not modified. Work remains uncommitted on `codex/m2-closure`.
