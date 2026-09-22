# M2 rerun fixes — 2026-09-22

**Ready for external verification; Codex executed no tests or checks.**

This round began with Astra's Call 4 abort report and incorporates the user's
later implemented test-suite revision. The revised coefficient, row-weight
operator and atom-evidence decisions remain in place. The two supplied revision
documents describe that work; they do not authorize Codex to execute their test
commands. The user's instruction to implement fixes and hand testing back
continues to control this round.

## Evidence and changes

1. **Completed runs were being enumerated again.** The earlier preserved
   [off driver log](../../llmoses/outputs/m2-runtime-rerun-20260922/off/driver.log)
   printed `(m2-result 3)` before returning to merge work. All three native logs
   recorded generations 1–3, an `ok` verdict, then a Call 4 fence abort.
   [runMoses](../../llmoses/deme/expand-deme.metta) and
   [sbResume](../../llmoses/wrapper/state-builder.metta) now enclose their
   side-effecting execution in `once`. The strict Python call fence is retained.

2. **The native bridge supplies flat behavioral-score lists.** The earlier
   checkpoints hold `mkBScore` with a flat list; terminal members had null
   bscores and every row-weight site had an empty support.
   [boundary.py](../../llmoses/utilities/boundary.py) now handles those flat
   lists as well as explicit Cons/cons spines. It unwraps mkBScore specifically
   so two-label lists remain intact. The shared fixture uses the native flat
   form; regression cases cover member/cull emission and weighted arithmetic.
   The construction-list adapter delegates to the same boundary helper.

3. **Canonical test configuration was missing.** Recent saved aborts, including
   [20260922-155445/CONTROL/abort](../../llmoses/outputs/runs/20260922-155445/CONTROL/abort),
   identify `complexity_coef` failing before generation 1 because no explicit
   selection temperature was supplied. The earlier working runtime logs also
   contain unspecialized-predicate messages, so those warnings alone do not
   identify the fatal error. [scripts/run-tests.py](../../scripts/run-tests.py)
   now supplies the closure config for LLMOSES entries when neither a config nor
   temperature was supplied, matching the smoke runners. Native entries and
   explicit operator settings retain their existing environment. Abort reasons
   are printed after durable artifact writes, and the runner retains stderr.

4. **The merge assertion compared integer and float terms.** The preserved
   [merge log](../../llmoses/outputs/m2-runtime-suite-rerun-20260922/merge/driver.log)
   shows subtraction of a 0.0 uniformity penalty followed by structural
   equality against integer -3. The compiled arithmetic implies -3.0, explaining
   the false comparison. The
   [fixture](../../llmoses/llmoses-tests/m2_merge_regression.metta) now checks
   both numeric bounds for exact equality to -3, without a tolerance or
   production-score rounding. It explicitly imports the Python bridge for
   standalone use. Scoring arithmetic and coefficient semantics are unchanged
   by this correction.

5. **Strategy game scores are not Boolean training rows.** Preserved strategy
   aborts identify an IndexError in Call 1; strategy seed and evaluated score
   vectors can have different lengths.
   [state_builder.py](../../llmoses/utilities/state_builder.py) now constructs
   row-weight payloads only for Boolean problems. Native strategy runs retain
   empty row weights; guided strategy remains unsupported. A new regression
   covers mixed vector lengths.

6. **The unreached battery stages had source-level defects.**
   [m2_runtime_test.sh](../../llmoses/llmoses-tests/m2_runtime_test.sh) translates
   checkpoint paths from the container mount to the host before calling the
   runner. Its pause controller has recorded ownership, cleanup and propagated
   failure status. Cold restore rejoins the persisted pause rather than
   creating a second checkpoint/pause event, and rejects a mismatched pause
   fence. A unit regression covers rejoining one pause.
   Site logs now include the causal position required by the trace checker;
   sequence IDs remain the identity. The
   [verifier](../../llmoses/llmoses-tests/live_agent_verify.py) checks runtime
   assertion failures and an executed PASS line instead of rejecting verbose
   printed definitions containing `Error`. It requires one pause/resume pair.

7. **The sr demo is unavailable on this upstream base.**
   [run_moses_demo.sh](../../run_moses_demo.sh) no longer schedules the missing
   continuous-regression entry under `demo all`. Help names the limitation;
   explicit `demo sr` returns a clear unavailable diagnostic and nonzero exit.
   This is a supported-demo inventory correction, not an implementation of
   continuous regression.

## Latest external results and remaining verification

The user's latest Docker report states: offline Python 84/84 passed; mutation
baseline 62/62 with seven mutants detected; canonical MeTTa 85/86; static checks
passed. The revised battery reached off, neutral, guided, identity and pair-policy
successfully, then stopped at the numeric merge assertion. The native expand
fixture and targeted strategy merge-cull-pressure passed. These are
**user-reported results for the state tested at that time**, not validation of
the subsequent changes above.

The current working tree still needs the offline/reverse suites, canonical
suite, smoke/demo runners and full revised Docker battery rerun. Use a fresh
output directory, for example:

```bash
bash llmoses/llmoses-tests/m2_runtime_test.sh llmoses/outputs/m2-runtime-next-20260922
```

That proposed directory has not been created. Bind-mount the current working
tree. Do not reuse earlier checkpoints with the changed protocol digest.
Standalone MeTTa invocations still require the explicit config; the canonical
and smoke runners supply it for their LLMOSES entries.

No acceptance claim is made for the unreached trace, full, cold-resume or final
verifier stages. Passing a unit checkpoint case cannot establish native
trajectory equality.

## Work record

[rerun-fix-commands.jsonl](rerun-fix-commands.jsonl) records all 82
shell commands and observed exits. They read sources, supplied documents and
existing artifacts; Python invocations only inspected saved JSON, without
importing or executing project code. One source/log search returned no matches;
another search named absent `BUILD_AND_RUN.md`. Neither was a test execution.
Edits were applied with `apply_patch`.

All supplied run artifacts remain untouched. No Docker container, provider,
background process, temporary directory or browser session was created. New
persistent documentation files are this handoff and its command journal.
Changes remain uncommitted on `codex/m2-closure`; the user's concurrent suite
revision and earlier working-tree changes were preserved.
