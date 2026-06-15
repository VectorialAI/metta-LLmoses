;; ============================================================================
;; llmoses/llmoses-tests/member-only-test.metta
;;
;; Member-loop-only integration check. Exercises ONLY the rewritten member
;; loop + a minimal flush — no knobs/deme (those remain unvalidated until this
;; passes). Decisive check: member B's bscore in state/run-1/step-1.json must
;; read [0.0, 1.0, 0.0, 1.0], and program_id must be stable (hashed from the
;; full raw tree, not the lossy preOrder display).
;;
;; All imports are repo-root-relative (no leading ../). run.sh is invoked from
;; the repo root, so CWD = /workspace/metta-moses and every path resolves
;; unambiguously regardless of where this file lives.
;;
;; extractors + state-builder loaded via import! (NOT load-ascii).
;; ============================================================================

;; ── metta-moses core preamble ──────────────────────────────────────────────
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

;; ── LLmoses additions ──────────────────────────────────────────────────────
!(import! &self llmoses/utilities/state-emitter)
!(import! &self llmoses/deme/expand-deme)

;; ── extractors + builder delegators under test (import!, NOT load-ascii) ───
!(import! &self llmoses/wrapper/extractors)
!(import! &self llmoses/wrapper/state-builder)

;; ============================================================================
;; FIXTURES — two exemplars with known cscores; mp is a 2-member OS.
;; Member B's bscore (Cons 0.0 (Cons 1.0 (Cons 0.0 (Cons 1.0 Nil)))) is the
;; decisive check: state/run-1/step-1.json must show "bscore": [0.0,1.0,0.0,1.0].
;; ============================================================================
(= (xA) (mkExemplar (mkTree (mkNode OR) Nil) (mkDemeId "1")
                    (mkCscore -0.2 1 0.1 0.1 -0.4)
                    (mkBScore (Cons 1.0 (Cons 0.0 (Cons 1.0 (Cons 1.0 Nil)))))))
(= (xB) (mkExemplar (mkTree (mkNode AND) (Cons (mkNullVex (Cons (mkTree (mkNode A) Nil) Nil))
                                               (Cons (mkNullVex (Cons (mkTree (mkNode B) Nil) Nil)) Nil)))
                    (mkDemeId "1")
                    (mkCscore -0.1 2 0.2 0.3 -0.6)
                    (mkBScore (Cons 0.0 (Cons 1.0 (Cons 0.0 (Cons 1.0 Nil)))))))
(= (mp) (ConsOS (xA) (ConsOS (xB) NilOS)))

;; ============================================================================
;; STAGED RUN — members only; no knobs, no deme meta.
;; ============================================================================
!(println! "MEMBER STAGE 1: new_run + begin_gen")
!(sbNewRun)
!(sbBeginGen 1)

!(println! "MEMBER STAGE 2: member loop (direct-native, emitGen pattern)")
!(sbEmitAllMembers 1 (mp))

!(println! "MEMBER STAGE 3: flush (writes step-1.json)")
!(sbFlushGen 1 "boolean" 3.5 20 5 2 1.0 5 0.004 50 2 "hillClimbing")

!(println! "MEMBER DONE: inspect state/run-1/step-1.json — check member B bscore == [0.0,1.0,0.0,1.0]")
