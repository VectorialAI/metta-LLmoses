;; ============================================================================
;; llmoses/llmoses-tests/os-length-probe.metta
;;
;; Probes whether OS.length reduces to a number in this scope, and in which
;; evaluation form — bare, eval-wrapped, let-bound, or let-bound+eval.
;; Also checks whether arithmetic/comparison reduce at all at top level, and
;; whether the exact failing if-guard shape reduces.
;;
;; All imports are repo-root-relative (no leading ../). Scope is identical to
;; member-only-test.metta so observations apply directly to the failing call site.
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

;; ── extractors + builder delegators (import!, NOT load-ascii) ───────────────
!(import! &self llmoses/wrapper/extractors)
!(import! &self llmoses/wrapper/state-builder)

;; ── FIXTURES — identical to member-only-test.metta ─────────────────────────
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
;; PROBES
;; ============================================================================

;; Does OS.length reduce to a number, and under which form?
;; Print each result so we can read what actually comes back.
!(println! (P1-bare        (OS.length (mp))))
!(println! (P2-eval         (eval (OS.length (mp)))))
!(println! (P3-letbind      (let* (($n (OS.length (mp)))) $n)))
!(println! (P4-letbind-eval (let* (($n (eval (OS.length (mp))))) $n)))

;; Is it specific to OS.length, or do arithmetic/comparison reduce at all here?
!(println! (P5-arith        (+ 1 1)))
!(println! (P6-compare      (>= 0 2)))

;; And the exact failing shape, in isolation — does the if-guard itself reduce?
!(println! (P7-guard        (if (>= 0 (eval (OS.length (mp)))) yes no)))
