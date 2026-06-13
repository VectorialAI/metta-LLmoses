;; ============================================================================
;; llmoses/llmoses-tests/state-builder-integration-test.metta
;;
;; FULL boundary test: members + knobs + deme + flush, two generations.
;; Loads EXACTLY like the working member-only test: root-relative import! for
;; everything (no ../, no load-ascii), run from repo root (CWD=/workspace/
;; metta-moses). That loading approach is what produced a real step-1.json
;; with correct per-member bscores; load-ascii + ../../../ produced an empty dir.
;;
;; SUCCESS:
;;   state/run-1/step-1.json  — 2 members, B bscore [0.0,1.0,0.0,1.0],
;;                              current_deme.knobs populated (2 knobs, mult 3),
;;                              deme_id "1", neighborhood_size 4
;;   state/run-1/step-2.json  — lineage: (OR (NOT A) B) new, AND-member culled,
;;                              (OR) persists
;; ============================================================================

;; ── metta-moses core preamble (root-relative) ──────────────────────────────
!(import! &self utilities/general-helpers)
!(import! &self utilities/list-methods)
!(import! &self utilities/pair)
!(import! &self utilities/map)
!(import! &self utilities/ordered-multimap)
!(import! &self utilities/ordered-set)
!(import! &self utilities/ordered-multiset)
!(import! &self utilities/nodeId)
!(import! &self utilities/lazy-random-selector)
!(import! &self utilities/lru-cache)
!(import! &self reduct/boolean-reduct/rte-helpers)
!(import! &self reduct/boolean-reduct/cut-unnecessary-or)
!(import! &self reduct/boolean-reduct/cut-unnecessary-and)
!(import! &self reduct/boolean-reduct/n-ary-propagate-not)
!(import! &self reduct/boolean-reduct/n-ary-gather-junctors)
!(import! &self reduct/boolean-reduct/delete-inconsistent-handle)
!(import! &self reduct/boolean-reduct/zero-constraint-subsumption)
!(import! &self reduct/boolean-reduct/one-constraint-subsumption)
!(import! &self reduct/boolean-reduct/promote-common-constraints)
!(import! &self reduct/boolean-reduct/reduce-to-elegance)
!(import! &self utilities/tree)
!(import! &self feature-selection/feature-selection-helpers)
!(import! &self feature-selection/select-top-features)
!(import! &self feature-selection/similarity-scorers)
!(import! &self feature-selection/simple)
!(import! &self feature-selection/smd)
!(import! &self feature-selection/incremental)
!(import! &self feature-selection/hc)
!(import! &self feature-selection/random-feature-selection)
!(import! &self feature-selection/feature-selection-main)
!(import! &self representation/knob-representation)
!(import! &self representation/lsk)
!(import! &self representation/logical-probe)
!(import! &self representation/logical-canonize)
!(import! &self representation/sample-logical-perms)
!(import! &self representation/add-logical-knobs)
!(import! &self representation/build-logical)
!(import! &self representation/build-knobs)
!(import! &self representation/knob-mapper)
!(import! &self representation/representation)
!(import! &self representation/create-representation)
!(import! &self scoring/strategy-score-cache)
!(import! &self examples/tic-tac-toe/tic-tac-toe-helpers)
!(import! &self examples/tic-tac-toe/random-player)
!(import! &self examples/tic-tac-toe/minimax-player)
!(import! &self examples/tic-tac-toe/game-engine)
!(import! &self examples/tic-tac-toe/moves)
!(import! &self examples/tic-tac-toe/moses-player)
!(import! &self examples/tic-tac-toe/strategy-scoring)
!(import! &self scoring/cacheSpace)
!(import! &self scoring/fitness)
!(import! &self scoring/bscore)
!(import! &self scoring/cscore)
!(import! &self scoring/complexity-based-scorer)
!(import! &self optimization/hillclimbing/cross-top-one-helpers)
!(import! &self optimization/hillclimbing/cross-top-one)
!(import! &self optimization/hillclimbing/hill-climbing-helpers)
!(import! &self deme/create-deme)
!(import! &self moses/neighborhood-sampling)
!(import! &self metapopulation/exemplar-type)
!(import! &self metapopulation/exemplar-selection)
!(import! &self metapopulation/metapopulation)
!(import! &self representation/instance)
!(import! &self deme/deme-id-creation)
!(import! &self deme/score-deme)
!(import! &self deme/merge-demes)

;; ── LLMOSES additions ───────────────────────────────────────────────────────
!(import! &self llmoses/utilities/state-emitter)
!(import! &self llmoses/deme/expand-deme)

;; ── extractors + builder delegators under test (import!, root-relative) ─────
!(import! &self llmoses/wrapper/extractors)
!(import! &self llmoses/wrapper/state-builder)

;; canary: prints the run dir if the builder module loaded (import-time I/O ran)
!(py-call (state_builder.sb_run_dir))

;; ============================================================================
;; FIXTURES — same xA/xB/mp as the (passing) member-only test, plus the
;; suite's (deme), and a gen-2 metapop that swaps the AND-member for an OR-NOT
;; member so the lineage diff has something to show.
;; ============================================================================
(= (xA) (mkExemplar (mkTree (mkNode OR) Nil) (mkDemeId "1")
                    (mkCscore -0.2 1 0.1 0.1 -0.4)
                    (mkBScore (Cons 1.0 (Cons 0.0 (Cons 1.0 (Cons 1.0 Nil)))))))
(= (xB) (mkExemplar (mkTree (mkNode AND) (Cons (mkNullVex (Cons (mkTree (mkNode A) Nil) Nil))
                                               (Cons (mkNullVex (Cons (mkTree (mkNode B) Nil) Nil)) Nil)))
                    (mkDemeId "1")
                    (mkCscore -0.1 2 0.2 0.3 -0.6)
                    (mkBScore (Cons 0.0 (Cons 1.0 (Cons 0.0 (Cons 1.0 Nil)))))))
;; gen-2 new member: an OR-rooted tree distinct from xA/xB.
(= (xC) (mkExemplar (mkTree (mkNode OR) (Cons (mkNullVex (Cons (mkTree (mkNode A) Nil) Nil))
                                              (Cons (mkNullVex (Cons (mkTree (mkNode B) Nil) Nil)) Nil)))
                    (mkDemeId "1")
                    (mkCscore -0.05 2 0.2 0.1 -0.25)
                    (mkBScore (Cons 1.0 (Cons 1.0 (Cons 0.0 (Cons 1.0 Nil)))))))
(= (mp)  (ConsOS (xA) (ConsOS (xB) NilOS)))   ; gen 1: A, B
(= (mp2) (ConsOS (xA) (ConsOS (xC) NilOS)))   ; gen 2: A persists, B->C

;; (deme) verbatim from expand-demes-test.metta — two mkLSK knobs, mult 3.
(= (deme) (mkDeme (mkRep (mkKbMap (mkDscKbMp (ConsMap ((mkNodeId (1)) 0) (ConsMap ((mkNodeId (2)) 1) NilMap))) (mkDscMp (ConsMMap ((mkDiscSpec 3) (mkLSK (mkDiscKnob (mkKnob  (mkNodeId (1))) (mkMultip 3) (mkDiscSpec 0) (mkDiscSpec 0) Nil))) (ConsMMap ((mkDiscSpec 3) (mkLSK (mkDiscKnob (mkKnob (mkNodeId (2))) (mkMultip 3) (mkDiscSpec 0) (mkDiscSpec 0) Nil))) NilMMap)))) (mkTree (mkNode AND) (Cons (mkNullVex (Cons (mkTree (mkNode A) Nil) Nil)) (Cons (mkNullVex (Cons (mkTree (mkNode B) Nil) Nil)) Nil)))) (mkSInstSet Nil) (mkDemeId "1")))
(= (demeRep)  (let (mkDeme $rep $sInst $demeId) (deme) $rep))
(= (demeIdOf) (let (mkDeme $rep $sInst $demeId) (deme) $demeId))

;; ============================================================================
;; GEN 1 — full: members + knobs + deme + flush.
;; ============================================================================
!(println! "INTEG STAGE 1: new_run")
!(sbNewRun)

!(println! "INTEG STAGE 2: gen1 members")
!(sbBeginGen 1)
!(sbEmitAllMembers 1 (mp))

!(println! "INTEG STAGE 3: gen1 knobs")
!(sbEmitAllKnobs 1 (demeRep))

!(println! "INTEG STAGE 3b: set selection to xA's tree (isolation check)")
!(println! "SELECTION: set selection to xA's tree")
!(sbSetSelection (mkTree (mkNode OR) Nil))

!(println! "INTEG STAGE 4: gen1 set_deme + flush")
!(sbSetDeme 1 (demeIdOf) (demeRep) 33)
!(sbFlushGen 1 "boolean" 3.5 20 5 2 1.0 5 0.004 50 2 "hillClimbing")

;; ============================================================================
;; GEN 2 — all-in-one path; mp2 drives the lineage diff.
;; ============================================================================
!(println! "INTEG STAGE 5: gen2 sbEmitGeneration (all-in-one)")
!(sbEmitGeneration 2 (mp2) (demeIdOf) (demeRep) 6
                   "boolean" 3.5 20 5 2 1.0 5 0.004 50 2 "hillClimbing")

!(println! "INTEG DONE: inspect state/run-1/step-1.json (members+knobs) and step-2.json (lineage)")

;; ============================================================================
;; PREORDER PROBE — does preOrder render real (non-mkNullVex) children?
;; The test fixtures above use mkNullVex placeholders, so the (OR) output in
;; step-2.json may be correct for those fixtures; this probe settles whether
;; preOrder flattens a REAL expanded tree (direct mkTree children) the same way.
;; ============================================================================
!(import! &self "probe_bscore.py")

;; Real direct-child tree: OR(A, B) with no mkNullVex wrapper.
!(py-call (probe_bscore.show "preOrder-real-tree"
   (eval (preOrder (mkTree (mkNode OR)
                    (Cons (mkTree (mkNode A) Nil)
                     (Cons (mkTree (mkNode B) Nil) Nil)))))))

;; mkNullVex-wrapped fixture shape (same as xA/xB/xC above), for contrast.
!(py-call (probe_bscore.show "preOrder-nullvex-tree"
   (eval (preOrder (mkTree (mkNode OR)
                    (Cons (mkNullVex (Cons (mkTree (mkNode A) Nil) Nil))
                     (Cons (mkNullVex (Cons (mkTree (mkNode B) Nil) Nil)) Nil)))))))
