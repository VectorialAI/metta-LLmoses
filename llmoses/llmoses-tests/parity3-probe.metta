;; LLMOSES parity-3 end-to-end probe.
;; Runs the full parity-3 (3-bit XOR) evolutionary exercise in isolation:
;;   nDeme=3, fs-algo=smd, maxGen=15, 8-row truth table.
;;
;; Run via:   ./run_moses_demo.sh parity3
;;
;; This is intentionally separate from expand-demes-test.metta so the main
;; assertEqual suite does not stall on this slow 15-generation run.

;; ── imports (identical to expand-demes-test.metta) ────────────────────────
;; ── generic utilities ────────────────────────────────────────────────────
!(import! &self utilities/general-helpers)
!(import! &self llmoses/utilities/general-helpers)
!(import! &self utilities/list-methods)
!(import! &self utilities/pair)
!(import! &self utilities/map)

!(import! &self utilities/ordered-multimap)
!(import! &self utilities/ordered-set)
!(import! &self utilities/ordered-multiset)

!(import! &self utilities/nodeId)
!(import! &self utilities/lazy-random-selector)
!(import! &self utilities/lru-cache)

;; ── boolean reduct ───────────────────────────────────────────────────────
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

;; ── tree, needed by scoring and representation ───────────────────────────
!(import! &self utilities/tree)

;; ── scoring: must precede FS because select-top-features/getUniPen uses cscore ─
!(import! &self scoring/strategy-score-cache)
!(import! &self scoring/cacheSpace)
!(import! &self scoring/fitness)
!(import! &self scoring/bscore)
!(import! &self scoring/cscore)
!(import! &self scoring/complexity-based-scorer)

;; ── feature selection: must precede representation.metta ─────────────────
!(import! &self feature-selection/feature-selection-helpers)
!(import! &self llmoses/feature-selection/similarity-scorers)
!(import! &self llmoses/feature-selection/select-top-features)
!(import! &self feature-selection/simple)
!(import! &self feature-selection/smd)
!(import! &self feature-selection/incremental)
!(import! &self feature-selection/hc)
!(import! &self feature-selection/random-feature-selection)
!(import! &self feature-selection/feature-selection-main)

;; ── representation / knob layer: must come after FS ──────────────────────
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
!(import! &self representation/instance)

;; ── example-specific scoring/game code ───────────────────────────────────
!(import! &self examples/tic-tac-toe/tic-tac-toe-helpers)
!(import! &self examples/tic-tac-toe/random-player)
!(import! &self examples/tic-tac-toe/minimax-player)
!(import! &self examples/tic-tac-toe/game-engine)
!(import! &self examples/tic-tac-toe/moves)
!(import! &self examples/tic-tac-toe/moses-player)
!(import! &self examples/tic-tac-toe/strategy-scoring)

;; ── optimizers ───────────────────────────────────────────────────────────
!(import! &self optimization/hillclimbing/cross-top-one-helpers)
!(import! &self optimization/hillclimbing/cross-top-one)
!(import! &self optimization/hillclimbing/hill-climbing-helpers)

;; ── deme / metapopulation ────────────────────────────────────────────────
!(import! &self deme/create-deme)
!(import! &self moses/neighborhood-sampling)

!(import! &self metapopulation/exemplar-type)
!(import! &self metapopulation/exemplar-selection)
!(import! &self metapopulation/metapopulation)

!(import! &self deme/deme-id-creation)
!(import! &self deme/score-deme)
!(import! &self llmoses/deme/merge-demes)

;; ── llmoses wrapper / run layer ──────────────────────────────────────────
!(import! &self llmoses/utilities/state-emitter)
!(import! &self llmoses/deme/expand-deme)
!(import! &self llmoses/wrapper/extractors)
!(import! &self llmoses/wrapper/state-builder)

;; ── demo data last ───────────────────────────────────────────────────────
!(import! &self moses/demo-problems)

;; ── helpers used only for printing results ───────────────────────────────
(= (printExemplar (mkExemplar $tree $demeId $cscore $bscore)) (println! (Tree: (preOrder $tree) CScore: $cscore Bscore: $bscore)))

;; ── seed metapopulation ──────────────────────────────────────────────────
;; AND with worst score; bscore length 8 matches the 8-row parity-3 table.
(= (parity3MetaPop)
   (ConsOS
     (mkExemplar
       (mkTree (mkNode AND) Nil)
       (mkDemeId "1")
       (mkCscore -8 2 1.0 0.0 -8.0)
       (mkBScore (Cons -1 (Cons -1 (Cons -1 (Cons -1 (Cons -1 (Cons -1 (Cons -1 (Cons -1 Nil))))))))))
     NilOS))

;; ── parity-3 (3-bit XOR) integration run ────────────────────────────────
;; (parity3) defined in moses/demo-problems.metta: 8 rows, labels X1 X2 X3 Out.
;; Target: (OR (AND X1 (NOT X2) (NOT X3)) (AND (NOT X1) X2 (NOT X3))
;;             (AND (NOT X1) (NOT X2) X3) (AND X1 X2 X3))
!(let*
   (
    ($result (runMoses
               15                             ;; maxGen
               (mkCscore 0 3 1.0 0.0 0)       ;; maxScore: perfect fit, complexity<=3
               6                              ;; maxCandOutput
               (parity3MetaPop)               ;; seed metapop
               0 3                            ;; nExpansion, nDeme
               (False None                     ;; prune-exemplar, fs-algo
                (eval (createTruthTableBScore 2 (parity3)))  ;; truthTableBScore
                (parity3))                    ;; itable
               hillClimbing                   ;; optimizer
               100 10 2 1                     ;; nEval, maxCandsPerDeme, minPoolSize, complexityTemp
               6 0.004 1000))                 ;; nToKeep, capCoef, genCount
    ($_ (println! ""))
    ($_ (println! "=== parity-3 top candidates ==="))
    ($_ (mapG printExemplar $result))
   )
   (OS.length $result)
 )
