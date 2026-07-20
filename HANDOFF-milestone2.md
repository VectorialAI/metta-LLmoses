# LLMOSES Milestone-2 Handoff (2026-07-13; updated 2026-07-18)

> **SUPERSEDED as the entry point: read `HANDOFF-milestone2-D033.md` first** — it pins
> this doc as the base state and carries the full 2026-07-18/19 session delta.
> The note below is the short form of the same session.

> **2026-07-18 session (D-033, uncommitted at time of writing — commit same-day!):**
> resolution audit of the m1 sim (53 handshakes; exemplar 4,374/4,374 and culling
> 1,262/1,262 flow through; 940 pair_utilities + 52 string ratio deltas were dropped
> silently) led to: (1) **contextual atom-prior lever_weights + combination_synergy
> IMPLEMENTED** (new fork `llmoses/representation/add-logical-knobs.metta` threads
> node op + tree path into `begin_combo_draw`; axes polarity/clause_type/
> parent_operator/tree_depth/selected_exemplar/combination_synergy; all-zero =
> global-only, byte-preserved); (2) strict stdlib validator
> `llmoses/utilities/utility_schema.py` — watcher validates before writing, ingest
> logs `schema_ok`/`ignored` so nothing drops silently; (3) agent-facing docs synced
> (ROLE.md + templates had still taught the legacy pair_utilities schema);
> (4) `utility_policy_test.sh` now 12 phases / 39 assertions (CTXOP, CTXDEPTH,
> CTXPOL, SYNERGY + off-switch converses), all green in-container;
> (5) `llmoses/llmoses-tests/resolution_regression_test.py` (37 assertions, no
> PeTTa needed) pins the m1 fixtures' survivor counts + ignored maps via tracked
> fixtures in `llmoses/llmoses-tests/fixtures/m1-sim-utilities/`. Changelog draft
> for the next doc revision: `llmoses/design-spec/v20-changelog-draft.md`.
> Ratio-string decision: rejected by design — the live agent constrained-generates
> `{direction, magnitude}` via the validator; no ingest leniency. Polarity is
> order-encoded at the boolean draw (2 of 4 sign patterns); full polarity control
> is a knob-stage lever (D-025), documented out of scope.

Continuation doc for a fresh chat context. Repo: `MortimerE/metta-LLmoses`, branch **`milestone-2`**, HEAD **`0d522b5`**, working tree clean. Untracked by choice: `llmoses_wrapper_design_v18.docx`, `llmoses_wrapper_design_v19.docx` (both are **plain UTF-8 markdown** despite the extension — copy to `.md` to edit with tooling that gates on extension), and this file. Companion state also lives in the Claude memory dir (`phase2-handshake-status`, `design-doc-conventions`) and the Codex vault under label `metta-llmoses/milestone2-handoff`.

## State: Phase II is IMPLEMENTED and PROVEN

Commit chain (each stage validated in-container before the next): `f51c8a8` handshake + capture fail-flags → `efb5695` probes deleted after foothold proven → `3a936b2` Step A ingestion + switches → `1538efd` lever 1 exemplar → `60a58c5` levers 2+3 culling/comparator → `0056dea` lever 5 atom prior → `0d522b5` durable test suite + agent-facing docs. (Lever 4 ratio validation rode in the Step A wiring.)

**Latest independent verification** (Codex-executed, fresh at HEAD; report at `llmoses/outputs/harness-verify-report.txt`): TRANSPORT 9/9, POLICY 27/27 across 8 phases, boolean smoke 5/5, strategy smoke 6/6 — hooks in place, firing, and demonstrably controlling the meta policy, with off-switch converses proving native behavior when disabled.

## The mechanism in one paragraph

The watcher's UtilityResponse to generation G is ingested when MOSES unblocks at the end of G (`sbAwaitResponse` → `state_builder.await_response` → `_ingest_utilities`; `pass:true` clears the buffer) and applied to G+1's draws. Two env switch planes recorded in `run_config.json.lever_switches`: `LLMOSES_EMIT_LEVERS` (outbound sections; default all) and `LLMOSES_APPLY_LEVERS` + `LLMOSES_LEVER_WEIGHT_<NAME>` (inbound; default EMPTY = pure shadow). One mixing rule everywhere: `w' = w_native·(λ·u^(1/T) + (1−λ))` — λ=0 exactly native, λ=1 with 0/1 utilities explicit control; missing ids neutral; all-zero pools degrade to native with `bias_degraded` rows. Audit vocabulary in `moses_native_log.jsonl`: `utility_ingest`, `bias_applied`, `bias_degraded`, `combo_pick`, `response_timeout`, plus per-gen `comparator_overrides`.

## Seam map (file → function)

| Lever | MeTTa seam | Python entry |
|---|---|---|
| Handshake | `llmoses/deme/expand-deme.metta` runMosesLoop: `sbAwaitResponse`, `sbLogUtilities` | `await_response`, `utility_summary` |
| Exemplar | `llmoses/metapopulation/exemplar-selection.metta` fork: `sbStreamSelCands` | `begin_selection` / `add_selection_candidate` / `select_index` |
| Cull draw | `llmoses/metapopulation/metapopulation.metta` fork: `cullAtRandom` + `sbStreamCullCands` | `begin_cull` / `add_cull_member` / `cull_index` |
| Dominated escape | `llmoses/deme/merge-demes.metta`: `sbDominatedEscape` at both `removeDominatedRec` drop points | `dominated_escape` |
| Comparator | metapopulation fork: `compareExemplar` (sentinel-2 native fallback) + `llmResortMetapop`; loop hook `comparator_resort_active` | `compare_exemplars` |
| Ratio | expand-deme fork: `llmRebuildContext`, `$ctx2` threading | `current_complexity_ratio` (consume-once per response) |
| Atom prior | `llmoses/representation/sample-logical-perms.metta` fork: `llmWeightedSelector` at both draw sites | `begin_combo_draw` / `weighted_combo_pick` |

All guidance code lives in `llmoses/utilities/state_builder.py` (end section "Phase II utility guidance"). Watcher mock modes: `llmoses/utilities/llmoses_watcher.py` `LLMOSES_MOCK_UTILITY_MODE` = neutral | ingest_probe | force_worst | cull_targets | retain_all | reverse_order | ratio_increase | atom_pair. Entry files (`llmoses/llmoses-tests/*.metta`) import forks at the base files' slots (D-FSFORK/D-FSLOAD).

## Running the proofs

```sh
docker run --rm -v "$PWD:/workspace/metta-moses" -w /workspace/metta-moses metta-llmoses bash llmoses/llmoses-tests/phase2_handshake_test.sh
docker run --rm -v "$PWD:/workspace/metta-moses" -w /workspace/metta-moses metta-llmoses bash llmoses/llmoses-tests/utility_policy_test.sh
docker run --rm -v "$PWD:/workspace/metta-moses" -w /workspace/metta-moses metta-llmoses bash -lc 'unset LLMOSES_AWAIT_RESPONSE; ./run_boolean_smoke_test.sh all'   # and run_strategy_smoke_test.sh
```
Inside `bash -lc`, `run.sh` is not on PATH — locate via `command -v run.sh || /opt/PeTTa/run.sh`. Ad-hoc run dirs: set `LLMOSES_RUN_DIR` under the workspace mount (host mktemp dirs may not be Docker-shared).

## Design decisions to know (documented in design doc v19, §5.1.8 + changelog)

- **D-029** handshake + capture fail-flags (`capture_status` per step, `capture_failures` run total; §5.1.7 invariant inverted only behind the deadman).
- **D-030** application layer (timing, switches, formula, audit).
- **D-031** comparator applies by **re-sorting the known population** at generation top — merge inserts always involve candidates born after the response, so both-ids ordering is structurally dead at insert time. Comparator λ is binary.
- **D-032** `culling_utilities` wildcard `{"program_id":"*"}` default retention — same newborn-timing asymmetry, culling side. Any future pid-keyed lever must handle this asymmetry.

## Known gaps / next steps (in priority order)

1. **Live-agent handback**: the watcher is still the mock estimator. The seam is exactly the UtilityResponse contract (`llmoses/skills/UTILITY_RESPONSE.md`) enforced by `utility_schema.validate_utility_response` (the agent's constrained-decoding/retry gate); an agent replacing `_mock_utility` needs no wrapper changes.
2. **Guided-vs-baseline experiments** per design doc §8.2.4 (convergence, quality, overhead, ablation, provider comparison) — includes **λ default tuning** (currently 1.0 when a lever is in the apply set) and revisiting **dominated-escape vacuity** at experiment scale (unit-proven; demo fixtures produce zero native dominance events).
3. ~~Contextual atom-prior `lever_weights`~~ **DONE 2026-07-18 (D-033)** — contextual entries + combination_synergy applied at the draw site; see header note. Deliberately not wired here: full polarity control (knob-stage lever per D-025).
4. **Design docs**: v19 (in `llmoses/design-spec/`, no longer at repo root) not yet uploaded to the Claude.ai "llmoses" project — Edward distributes; fold `llmoses/design-spec/v20-changelog-draft.md` into the next revision.

## Operational gotchas (learned the hard way)

- **Commit same-day.** On 2026-07-12 an unknown external process bulk-overwrote three files, destroying then-uncommitted handshake work (recovered from session context). Never leave multi-day work uncommitted here.
- **codex-delegate tools do not return final report text** — always have Codex write reports to a file (gitignored `llmoses/outputs/` works) and read it.
- **PeTTa boundary rules still bite**: py-call args must be let*-bound (D-017-A2); never rebind a `$var` in a let* (use fresh names like `$ctx2`); scalar returns only across py-call (all bias sites return ints/floats; lists stream per-member).
- Design docs: `.docx` extension, literally markdown; Read tool refuses the extension.
