
;; LLMOSES entry-point for the expand-deme test suite.
;; Overlay of deme/tests/expand-demes-test.metta:
;;   1. Imports are root-relative (CWD = repo root when run via run.sh).
;;   2. llmoses/wrapper/state-builder and llmoses/deme/expand-deme replace the
;;      upstream versions (runMosesLoop-aware).
;; Dead upstream fixtures that no live assertEqual referenced (metaPop, ortable,
;; orttable, bigtable*) were removed; xortable is kept because expand-example
;; extracts the commented XOR block.
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

;; ── feature selection / representation ──────────────────────────────────
!(import! &self feature-selection/feature-selection-helpers)
!(import! &self llmoses/feature-selection/similarity-scorers)
!(import! &self llmoses/feature-selection/select-top-features)
!(import! &self feature-selection/simple)
!(import! &self feature-selection/smd)
!(import! &self feature-selection/incremental-feature-selection)
!(import! &self feature-selection/hc)
!(import! &self feature-selection/random-feature-selection)
!(import! &self feature-selection/feature-selection-main)

;; ── representation / knob layer: after FS ────────────────────────────────
!(import! &self representation/knob-representation)
!(import! &self representation/lsk)
!(import! &self representation/disc-probe)
!(import! &self representation/logical-probe)
!(import! &self representation/logical-canonize)
!(import! &self llmoses/representation/sample-logical-perms)
!(import! &self llmoses/representation/add-logical-knobs)
!(import! &self llmoses/representation/build-logical)
!(import! &self representation/build-knobs)
!(import! &self representation/knob-mapper)
!(import! &self llmoses/representation/representation)
!(import! &self llmoses/representation/create-representation)
!(import! &self representation/instance)

;; ── example-specific scoring/game code ───────────────────────────────────
!(import! &self scoring/strategy-score-cache)
!(import! &self examples/tic-tac-toe/tic-tac-toe-helpers)
!(import! &self examples/tic-tac-toe/random-player)
!(import! &self examples/tic-tac-toe/minimax-player)
!(import! &self examples/tic-tac-toe/game-engine)
!(import! &self examples/tic-tac-toe/moves)
!(import! &self examples/tic-tac-toe/moses-player)
!(import! &self examples/tic-tac-toe/strategy-scoring)

;; Scorers reference representation and strategy definitions during PeTTa
;; specialization, so keep the upstream import order.
!(import! &self scoring/cacheSpace)
!(import! &self scoring/fitness)
!(import! &self llmoses/scoring/bscore)
!(import! &self llmoses/scoring/cscore)
!(import! &self llmoses/scoring/complexity-based-scorer)
!(import! &self llmoses/wrapper/extractors)

;; ── optimizers ───────────────────────────────────────────────────────────
!(import! &self optimization/hillclimbing/cross-top-one-helpers)
!(import! &self llmoses/optimization/cross-top-one)
!(import! &self llmoses/optimization/hill-climbing-helpers)

;; ── deme / metapopulation ────────────────────────────────────────────────
!(import! &self deme/create-deme)
!(import! &self llmoses/moses/neighborhood-sampling)

!(import! &self metapopulation/exemplar-type)
!(import! &self llmoses/metapopulation/exemplar-selection)
!(import! &self llmoses/metapopulation/metapopulation)

!(import! &self deme/deme-id-creation)
!(import! &self deme/score-deme)
!(import! &self llmoses/deme/merge-demes)

;; ── llmoses wrapper / run layer ──────────────────────────────────────────
!(import! &self llmoses/wrapper/state-builder)
!(import! &self llmoses/deme/expand-deme)

;; ── demo data last ───────────────────────────────────────────────────────
!(import! &self llmoses/moses/demo-problems)

!(callPredicate (Predicate (consult "moses/tests/rte-helpers-fast.pl")))

(= (deme) (mkDeme (mkRep (mkKbMap (mkDscMp (((mkDiscSpec 3) (mkLSK (mkDiscKnob (mkMultip 3) (mkDiscSpec 0) (mkDiscSpec 0) ()))) ((mkDiscSpec 3) (mkLSK (mkDiscKnob (mkMultip 3) (mkDiscSpec 0) (mkDiscSpec 0) ())))))) (mkTree (mkNode AND) (cons (mkKnob (mkNullVex (cons (mkTree (mkNode A) ()) ())) (mkLSK (mkDiscKnob (mkMultip 3) (mkDiscSpec 0) (mkDiscSpec 0) ())) 0) (cons (mkKnob (mkNullVex (cons (mkTree (mkNode B) ()) ())) (mkLSK (mkDiscKnob (mkMultip 3) (mkDiscSpec 0) (mkDiscSpec 0) ())) 1) ())))) (mkSInstSet ()) (mkDemeId "1")))
(= (table1) (eval (createTruthTableBScore 2 (mkITable
                         (cons (cons False (cons False (cons False ())))
                         (cons (cons True (cons False (cons False ())))
                         (cons (cons False (cons True (cons False ())))
                         (cons (cons True (cons True (cons True ()))) ()))))
                         (cons A (cons B (cons O ())))))))

(= (ttable1) (mkITable
                         (cons (cons False (cons False (cons False ())))
                         (cons (cons True (cons False (cons False ())))
                         (cons (cons False (cons True (cons False ())))
                         (cons (cons True (cons True (cons True ()))) ()))))
                         (cons A (cons B (cons O ())))))

(= (xortable) (mkITable
                         (cons (cons False (cons False (cons False ())))
                         (cons (cons True (cons False (cons True ())))
                         (cons (cons False (cons True (cons True ())))
                         (cons (cons True (cons True (cons False ()))) ()))))
                         (cons A (cons B (cons O ())))))

;; (= (metaPop2) (cons (mkExemplar (mkTree (mkNode AND) ()) (mkDemeId "1") (eval (worstCscore)) (mkBScore (cons -1 (cons -1 ())))) ()))
;; (= (metaPop2) (cons (mkExemplar (mkTree (mkNode AND) ()) (mkDemeId "1") (eval (worstCscore)) (mkBScore (cons -1 (cons -1 (cons -1 (cons -1 ())))))) ()))
(= (metaPop2) (cons (mkExemplar (mkTree (mkNode AND) ()) (mkDemeId "1") (mkCscore -4 2 1.0 0.0 -4.0) (mkBScore  (cons -1 (cons -1 (cons -1 (cons -1 ())))))) ()))

;; (: isScored (-> (ScoredInstance Cscore) Bool))
(= (isScored (mkSInst (mkPair $instance $score))) (~= $score (eval (worstCscore))))

;; Testcase for optimizeDemes
!(assertEqual
(let*
(
    ($optimizeDemesReturn (optimizeDemes (deme)
                (table1)
                (mkInst (cons 0 (cons 0 ())))
                hillClimbing
                ))
    ($_ (println! "optimizeDemes Returns"))
    ($_ (println! $optimizeDemesReturn))
    (($instance (mkDeme $rep (mkSInstSet $instSet) $id) $state) $optimizeDemesReturn)
    ($instanceCount (List.length $instSet))
    ($scoredElems (List.map isScored $instSet))
)
((>= $instanceCount 4) (List.any $scoredElems)))
(True True))

;; ;; Testcase for expandDeme INFO: For some reason this test case disturbs the next test case but is fine alone.
;; !(assertEqual
;; (let*
;; (
;;     ($updatedDeme (expandDeme (metaPop2) 0 1 False sim
;;                     (table1)
;;                     hillClimbing
;;                     (ttable1)
;;                     mi))
;;     ($updatedDemeLength (size-atom $updatedDeme)))
;; (>= $updatedDemeLength 1)) True)

;; Testcase for runMoses
!(assertEqual
(let*
(
    ($_ (println! (running started)))
    ($topCandidates (runMoses 2 (mkCscore -0.1 2 0.1 0.1 3) 3 (metaPop2) 0 2 (False sim
    (table1)
    (ttable1))
    hillClimbing 5 2 0 1
    3 0.004 1000))
    ($topCandidatesLength (OS.length $topCandidates))
)
(>= $topCandidatesLength 1)
) True)

;; Testcase for runMoses
!(assertEqual
(let*
(
    ($topCandidates (runMoses 1 (mkCscore -0.1 2 0.1 0.1 3) 3 (metaPop2) 0 2 (False rd
    (table1)
    (ttable1))
    hillClimbing 5 2 0 1
    3 0.004 1000))
    ($topCandidatesLength (OS.length $topCandidates))
)
(>= $topCandidatesLength 1)
) True)

;; Testcase for runMoses
!(assertEqual
(let*
(
    ($topCandidates (runMoses 1 (mkCscore -0.1 2 0.1 0.1 3) 3 (metaPop2) 0 2 (False inc
    (table1)
    (ttable1))
    hillClimbing 5 2 0 1
    3 0.004 1000))
    ($topCandidatesLength (OS.length $topCandidates))
)
(>= $topCandidatesLength 1)
) True)

;; Testcase 2 for runmoses.
;; When maxGen become 10, test number of returned instances is not greater than maxCandOutput,
;;              where maxCandOutput is 3 and minPoolSize is 2
!(assertEqual
(let $length
((OS.length (runMoses 10 (mkCscore -0.1 2 0.1 0.1 3) 3 (metaPop2) 0 2
    (False    ;; the new arguments for prune-exemplar -- we are saying dont prune the exemplar
    inc      ;; the new arguments for feature selection algo
    (eval (createTruthTableBScore 2 (mkITable
                          (cons (cons False (cons False (cons False ())))
                          (cons (cons True (cons False (cons False ())))
                          (cons (cons False (cons True (cons False ())))
                          (cons (cons True (cons True (cons True ()))) ()))))
                          (cons A (cons B (cons O ()))))))
    (mkITable
                          (cons (cons False (cons False (cons False ())))
                          (cons (cons True (cons False (cons False ())))
                          (cons (cons False (cons True (cons False ())))
                          (cons (cons True (cons True (cons True ()))) ()))))
                          (cons A (cons B (cons O ())))))
    hillClimbing 5 2 2 1
    3 0.004 1000)
    ))
        (> $length 3)
)
    False
)
;; Parameters:
  ;; $maxGen $maxScore $maxCandOutput $metaPop $nExpansion $nDeme
  ;; $prune-exemplar
  ;; $fs-algo
  ;; $truthTableBScore
  ;; $optimize
  ;; $nEval $maxCandsPerDeme $minPoolSize $complexityTemperature
  ;; $itable
  ;; $nToKeep $capCoef $genCount

;; The following configuration can result to XOR.
;; A⊕B=(A∨B)∧¬(A∧B)
;; (AND (OR A B) (OR (NOT A) (NOT B)))
;; A⊕B=(¬A∧B)∨(A∧¬B)
;; (AND (OR (AND A (NOT B)) (AND (NOT A) B)))
;; !(let*
;;    (
;;     ($result (runMoses 20 (mkCscore -0.1 2 0.1 0.1 3) 10 (metaPop2) 0 2
;;                   (False None (eval (createTruthTableBScore 2 (xortable))) (xortable))
;;                   hillClimbing
;;                   100 10 20 2
;;                   10 0.004 1000))
;;     ($nt (println! ""))
;;     ($newR (mapG cleanedExemplar $result))
;;     ($_ (mapG printExemplar $result))
;;    )
;;    $newR
;;  )
;;
;; metapop for testing
(= (strategyMetaPop)
   (cons
     (mkExemplar
       (mkTree (mkNode PRIORITIZED-OR)
         (cons (mkTree (mkNode playwin) ())
               (cons (mkTree (mkNode playblock) ()) ())))
       (mkDemeId "0")
       (mkCscore 2.0 2 0.57 0.0 1.43)
       (mkBScore (cons 2.0 ())))
     ()))

;; !(assertEqual ;; INFO: This test case is blocking the reset. But works fine on it's own.
;;    (let* (
;;      ($optimizedDemes (expandDeme
;;                         (strategyMetaPop)
;;                         0 1 5 3.5
;;                         (mkCscore 5.0 5 1.43 0.0 3.57)
;;                         hillClimbing))
;;      ($demeCount (size-atom $optimizedDemes))
;;    )
;;    (>= $demeCount 1))
;;    True)
;;
!(assertEqual
   (let* (
     ($result (runMoses
                1                              ;; maxGen
                (mkCscore 5.0 5 1.43 0.0 3.57) ;; target
                3                              ;; maxCandOutput
                (strategyMetaPop)              ;; metaPop
                0 1                            ;; nExpansion, nDeme
                (5 3.5)                          ;; nGames, complexity ratio
                hillClimbing                   ;; optimizer
                30 5 2 1.0                     ;; nEval, maxCands, minPool, temp
                5 0.004 1000))                 ;; nToKeep, capCoef, genCount
     ($resultSize (eval (OS.length $result)))
   )
   (>= $resultSize 1))
   True)

!(assertEqual
   (let* (
     ($result (runMoses
                1                              ;; maxGen
                (mkCscore 5.0 5 1.43 0.0 3.57) ;; target
                1                              ;; maxCandOutput
                (strategyMetaPop)              ;; metaPop
                0 1                            ;; nExpansion, nDeme
                (5 3.5)                          ;; nGames, complexity ratio
                hillClimbing                   ;; optimizer
                30 5 2 1.0                     ;; nEval, maxCands, minPool, temp
                5 0.004 1000))                 ;; nToKeep, capCoef, genCount
     ($topExemplar (eval (OS.getByIdx 0 $result)))
     ($topScore (eval (getExemplarCscore $topExemplar)))
     ($penScore (eval (getPenScore $topScore)))
     ;; Score should be better than worst possible
     ($isValid (> $penScore -1000.0))
   )
   $isValid)
   True)

;; ── Parity-3 / sbEmitCullCands stress example ────────────────────────────
;; Parity-3 (3-bit XOR): output is True when an odd number of {X1,X2,X3} are True.
;; Target canonical form: (OR (AND X1 (NOT X2) (NOT X3)) (AND (NOT X1) X2 (NOT X3))
;;                            (AND (NOT X1) (NOT X2) X3) (AND X1 X2 X3))
;;
;; Also available as an isolated run (no preceding assertEqual tests):
;;   ./run_moses_demo.sh parity3
;;
;; (parity3) is defined in moses/demo-problems.metta: 8 rows, labels X1 X2 X3 Out.
(= (parity3MetaPop)
   (cons
     (mkExemplar
       (mkTree (mkNode AND) ())
       (mkDemeId "1")
       (mkCscore -8 2 1.0 0.0 -8.0)
       (mkBScore (cons -1 (cons -1 (cons -1 (cons -1 (cons -1 (cons -1 (cons -1 (cons -1 ()))))))))))
     ()))

!(let*
   (
    ($result (runMoses
               15                             ;; maxGen
               (mkCscore 0 3 1.0 0.0 0)       ;; maxScore: perfect fit, complexity<=3
               6                              ;; maxCandOutput
               (parity3MetaPop)               ;; seed metapop
               0 3                            ;; nExpansion, nDeme
               (False smd                     ;; prune-exemplar, fs-algo
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
