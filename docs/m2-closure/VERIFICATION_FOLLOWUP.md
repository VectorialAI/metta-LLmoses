# Docker verification follow-up — 2026-09-22

**Ready for the next external run; no checks were rerun by Codex.**

The user supplied Astra's Docker report for image `metta-llmoses`
(`sha256:d6aa580c…`): MeTTa 85/86 passed; offline Python 36 passed / 5 failed;
failure injection 19 passed; handshake 12 passed; utility policy 13 passed;
three reverse mutants detected; static checks and the standalone merge fixture
passed. The native battery stopped during driver generation at an unmatched
Python parenthesis, before any Docker runs. These are user-reported results,
not independently reproduced here.

The user then explicitly instructed Codex to prepare the fixes and leave all
reruns to them. No Docker command, suite, battery, syntax/compiler check or
`git diff --check` was executed in this follow-up.

## Prepared corrections

- [overlay_imports_test.py](../../llmoses/llmoses-tests/overlay_imports_test.py):
  add `moses/neighborhood-sampling` to the additive-module allowlist. Its
  compatibility overlay intentionally imports native definitions and adds the
  legacy strategy representation overload.
- [m2_runtime_test.sh](../../llmoses/llmoses-tests/m2_runtime_test.sh):
  split merge-fixture input loading from output construction and remove the
  unmatched closing parenthesis in the embedded Python.
- [expand-demes-test.metta](../../llmoses/llmoses-tests/expand-demes-test.metta):
  load extractors before optimizer consumers and the state-builder wrapper
  before expansion; move strategy cache initialization before game/scoring
  definitions to follow the native entry's order; remove the nonexistent
  `llmoses/utilities/state-emitter` import.
- [strategy_test.metta](../../llmoses/llmoses-tests/strategy_test.metta):
  apply the same cache-order and stale-emitter corrections.
- Prepare two import regression tests covering missing direct MeTTa imports and
  dependency-before-consumer ordering. The pre-change entry points violate
  those assertions; execution remains pending.

The entry-point changes address concrete source discrepancies associated with
the specialization failure. Without rerunning PeTTa, resolution of the reported
`runMoses`/cache failure remains unconfirmed. No native source was modified.

## Rerun handoff

Use the updated working tree through the Docker bind mount so the image's copied
sources do not hide these edits. Rerun the affected import suite and
`expand-demes-test.metta`, then the M2 battery with a new output directory:

```bash
bash llmoses/llmoses-tests/m2_runtime_test.sh llmoses/outputs/m2-runtime-rerun-20260922
```

That output directory has not been created by this follow-up. Passing results,
native closure acceptance, and the remaining replay/calibration gates are still
pending external verification.

## Commands and resources

[followup-commands.jsonl](followup-commands.jsonl) records all 43
shell commands and their observed exit codes. They are source searches/reads
and Git status/diff inspection. One search included absent `tests` and
`.agents` directories; a subsequent native fixture read used
`deme/tests/expand-demes-test.metta`. Reading the missing emitter confirmed the
stale import. Two searches returned no matches. No test failure is inferred
from these inspection exits.

Source edits and this handoff were applied using `apply_patch`; those tool
operations are reflected in the working-tree files. No container, background
process, temporary directory or browser session was created. New persistent
follow-up artifacts are this file and `followup-commands.jsonl`; existing
handoff documents link here. The branch remains `codex/m2-closure`.
