# M2 closure re-audit

Latest external results and pending rerun repairs are recorded in
[RERUN_FIXES_20260922.md](RERUN_FIXES_20260922.md); they supersede the earlier
verification-status narrative without claiming closure acceptance.

This table records the original implementation handoff. Subsequent user-reported
Docker results and prepared, untested corrections are recorded separately in
[VERIFICATION_FOLLOWUP.md](VERIFICATION_FOLLOWUP.md).

Basis: staging/upstream-m1-m2-compat ea6ea730, hardening preservation 77df0fdf, implementation on codex/m2-closure. The original stash is retained. Revision 2 §0 governs the score-offset/conditional-policy redesign. The user's instruction to stop before testing overrides the plan's baseline/final verification sequence.

| Finding / group | Implementation disposition | Re-verification |
|---|---|---|
| H-001 / fork currency | Rebase basis already current; native source edits excluded | Deferred source/runtime comparison |
| R1–R4 | Already in preserved hardening layer; adapted to per-call fences, ownership and durable pause/abort | Prepared fixtures, unrun |
| F-003 / F-004 | Bounded score offsets through native temperature; identity zero; no absolute A | Unrun |
| F-020 / minPoolSize / F-017 / F-018 | Complete pool, deterministic feasible K, exact-K Madow; overflow subsumed and logged | Unrun |
| F-022 | Preserve incomparable accumulator entries when dominance pivot changes | Fixture written before fix; unrun |
| F-040 / D-DUPSLOT | Comparator lever removed, native E contract restored; no speculative ordered-set fix | E/identity fixture unrun |
| F-026 | Mean-one row multipliers; rescore stored bscore; emit unweighted score | Unrun |
| F-029 / F-031 | Conditional ordered-pair policy replaces aggregate/mask contract; token lifecycle | Causal/math/native trace fixtures unrun |
| U-001 | Native unify remains; union-free Jaccard workaround retained | Width>2 regression unrun |
| Overlay bypasses | Entries use add-logical-knobs, demo-problems, cscore and new build-logical overlay | Import regression unrun |
| Documentation contradictions | Four-call order, mix-before-sharpen, P8, score offsets and causal policy supersede earlier text | Document edits prepared |
| Remaining upstream defects | Native source unchanged; retain upstream report dispositions | No new empirical claims |

New causal finding: a parent and its appended swapped child share a native probe path, and earlier draws create later sites. Therefore a precomputed path mask is not a valid contract. The explicit overlay threads a separate causal path and site_kind; site identity is sequential. The prepared native draw trace must confirm recursion/draw order before experimental use.

No hardening, confidence, failure-injection, live-provider, Docker or native-runtime verification has been run for this implementation. Old green results apply only to their original commit, not this branch. M3 readiness remains gated on testing, native off equivalence, cold checkpoint replay, context-token measurement and baseline calibration.
