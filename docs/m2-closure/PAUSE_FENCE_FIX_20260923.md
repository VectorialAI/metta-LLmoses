# Pause-controller fence fix — 2026-09-23

Ready for external rerun. No tests, Docker runs, static checks or compilation
were executed during this repair.

The preserved generation-1 responses contain string `run_seq: "1"`. The native
log attributes all three schema failures to that field at calls 1, 2 and 4.
Call 3 was disabled in this arm. Native resume now completes generation 3, but
the earlier failures correctly persist in the degraded terminal verdict.

[m2_runtime_test.sh:66](../../llmoses/llmoses-tests/m2_runtime_test.sh#L66) now
uses the existing `call_paths.key(seq, step)` helper to convert all three fence
fields to integers. This replaces the manual conversion of only generation
and call. The production schema and acceptance thresholds remain unchanged.
The existing battery's requirement for an `ok` terminal covers this defect.

Rerun the battery from a fresh output directory, regenerating its controller
and checkpoint rather than resuming the already degraded checkpoint. Proposed
command (not executed; directory not created):

```bash
bash llmoses/llmoses-tests/m2_runtime_test.sh llmoses/outputs/m2-runtime-fence-20260923
```

The user's preceding Docker report records offline 92/92, reverse baseline
64/64 with seven mutants detected, canonical MeTTa 86/86, targeted strategy
`state single` and static checks passing. These are external results from
before this edit. Full strategy-wrapper completion remains unverified after
the reported cleanup exit 137 while entering `state empty-seed`; this repair
makes no claim about that duration issue.

[pause-fence-commands-20260923.jsonl](pause-fence-commands-20260923.jsonl)
records all 11 executed shell commands and observed outcomes; all were
successful source/Git/artifact reads. Edits used `apply_patch` for the battery,
this handoff, the implementation index and command journal. No containers,
watchers, temporary directories or browser sessions were created. Preserved
run artifacts were not modified. Work remains uncommitted on `codex/m2-closure`.
