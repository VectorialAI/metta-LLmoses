;; strategy_test.metta — focused tic-tac-toe strategy MOSES tests.
;;
;; This file intentionally defines callable test forms instead of running every
;; assertion at import time. The companion run_strategy_smoke_test.sh harness
;; imports this file and invokes one named test or all tests.
;;
;; Install location expected by the harness:
;;   llmoses/llmoses-tests/strategy_test.metta
;;
;; Classic MOSES -H demos (pa/dj/maj/mux/sr/cp/ann-cp) are not exercised here;
;; boolean demos: ./run_moses_demo.sh demo pa
;; strategy demo: ./run_moses_demo.sh demo ttt
;; this harness targets the tic-tac-toe strategy problem type instead.

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
!(import! &self scoring/strategy-score-cache)
!(import! &self scoring/cacheSpace)
!(import! &self scoring/fitness)
!(import! &self scoring/bscore)
!(import! &self llmoses/scoring/cscore)
!(import! &self llmoses/scoring/complexity-based-scorer)
!(import! &self feature-selection/feature-selection-helpers)
!(import! &self llmoses/feature-selection/similarity-scorers)
!(import! &self llmoses/feature-selection/select-top-features)
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
!(import! &self llmoses/representation/sample-logical-perms)
!(import! &self representation/add-logical-knobs)
!(import! &self representation/build-logical)
!(import! &self representation/build-knobs)
!(import! &self representation/knob-mapper)
!(import! &self llmoses/representation/representation)
!(import! &self llmoses/representation/create-representation)
!(import! &self representation/instance)
!(import! &self llmoses/wrapper/extractors)
!(import! &self examples/tic-tac-toe/tic-tac-toe-helpers)
!(import! &self examples/tic-tac-toe/random-player)
!(import! &self examples/tic-tac-toe/minimax-player)
!(import! &self examples/tic-tac-toe/game-engine)
!(import! &self examples/tic-tac-toe/moves)
!(import! &self examples/tic-tac-toe/moses-player)
!(import! &self examples/tic-tac-toe/strategy-scoring)
!(import! &self optimization/hillclimbing/cross-top-one-helpers)
!(import! &self optimization/hillclimbing/cross-top-one)
!(import! &self optimization/hillclimbing/hill-climbing-helpers)
!(import! &self deme/create-deme)
!(import! &self moses/neighborhood-sampling)
!(import! &self metapopulation/exemplar-type)
!(import! &self metapopulation/exemplar-selection)
!(import! &self metapopulation/metapopulation)
!(import! &self deme/deme-id-creation)
!(import! &self deme/score-deme)
!(import! &self llmoses/deme/merge-demes)
!(import! &self llmoses/wrapper/state-builder)
!(import! &self llmoses/utilities/state-emitter)
!(import! &self llmoses/deme/expand-deme)

;; Empty strategy metapop — empty PRIORITIZED-OR with worst CScore.
;; Useful for testing evolution from a cold strategy seed.
(= (emptyStrategyMetaPop)
   (ConsOS
     (mkExemplar
       (mkTree (mkNode PRIORITIZED-OR) Nil)
       (mkDemeId "0")
       (mkCscore -1000.0 0 0.0 0.0 -1000.0)
       (mkBScore (Cons -1000.0 Nil)))
     NilOS))

;; Non-empty strategy metapop used as the stable low-cost seed.
(= (strategyMetaPop)
   (ConsOS
     (mkExemplar
       (mkTree (mkNode PRIORITIZED-OR)
         (Cons (mkTree (mkNode playwin) Nil)
               (Cons (mkTree (mkNode playblock) Nil) Nil)))
       (mkDemeId "0")
       (mkCscore 2.0 2 0.57 0.0 1.43)
       (mkBScore (Cons 2.0 Nil)))
     NilOS))

;; Helpers for optional human-readable diagnostics.
(= (mapG $f NilOS) NilOS)
(= (mapG $f Nil) Nil)
(= (mapG $f ($ctor $x $xs)) ($ctor ($f $x) (mapG $f $xs)))
(= (printExemplar (mkExemplar $tree $demeId $cscore $bscore))
   (println! (Tree: (preOrder $tree) CScore: $cscore Bscore: $bscore)))
(= (cleanedExemplar (mkExemplar $tree $demeId $cscore (mkBScore $bscore)))
   ((preOrder $tree) (List.sum $bscore)))

;; -------------------------------------------------------------------------
;; MeTTa-level strategy tests. These mirror the boolean expand/run tests but
;; target the game-strategy overloads and stress the dimensions relevant to
;; SSK, strategy neighborhoods, game scoring, multi-deme, and multi-generation.
;; -------------------------------------------------------------------------

(= (strategyExpandSingleDemeTest)
   (let* (
     ($optimizedDemes (expandDeme
                        (strategyMetaPop)
                        0 1
                        5 random-player 3.5
                        (mkCscore 5.0 5 1.43 0.0 3.57)
                        hillClimbing))
     ($demeCount (size-atom $optimizedDemes)))
   (>= $demeCount 1)))

(= (strategyExpandMultiDemeTest)
   (let* (
     ($optimizedDemes (expandDeme
                        (strategyMetaPop)
                        0 2
                        5 random-player 3.5
                        (mkCscore 5.0 5 1.43 0.0 3.57)
                        hillClimbing))
     ($demeCount (size-atom $optimizedDemes)))
   (>= $demeCount 2)))

(= (strategyRunSingleGenerationTest)
   (let* (
     ($result (runMoses
                1
                (mkCscore 5.0 5 1.43 0.0 3.57)
                3
                (strategyMetaPop)
                0 1
                (5 random-player 3.5)
                hillClimbing
                30 5 2 1.0
                5 0.004 1000))
     ($resultSize (eval (OS.length $result))))
   (>= $resultSize 1)))

(= (strategyRunMaxCandidateCapTest)
   (let* (
     ($result (runMoses
                1
                (mkCscore 5.0 5 1.43 0.0 3.57)
                1
                (strategyMetaPop)
                0 1
                (5 random-player 3.5)
                hillClimbing
                30 5 2 1.0
                5 0.004 1000))
     ($resultSize (eval (OS.length $result))))
   (<= $resultSize 1)))

(= (strategyGameContextScoringTest)
   (let* (
     ($result (runMoses
                1
                (mkCscore 5.0 5 1.43 0.0 3.57)
                1
                (strategyMetaPop)
                0 1
                (7 random-player 4.25)
                hillClimbing
                30 5 2 1.0
                5 0.004 1000))
     ($topExemplar (eval (OS.getByIdx 0 $result)))
     ($topScore (eval (getExemplarCscore $topExemplar)))
     ($penScore (eval (getPenScore $topScore))))
   (> $penScore -1000.0)))

(= (strategyRunMultiGenerationMultiDemeTest)
   (let* (
     ($result (runMoses
                3
                (mkCscore 5.0 5 1.43 0.0 3.57)
                3
                (strategyMetaPop)
                0 2
                (5 random-player 3.5)
                hillClimbing
                30 5 2 1.0
                5 0.004 1000))
     ($resultSize (eval (OS.length $result))))
   (>= $resultSize 1)))

(= (strategyRunEmptySeedTest)
   (let* (
     ($result (runMoses
                2
                (mkCscore 10.0 0 0 0.0 10)
                3
                (emptyStrategyMetaPop)
                0 2
                (10 random-player 3.5)
                hillClimbing
                30 5 2 1.0
                5 0.004 1000))
     ($resultSize (eval (OS.length $result))))
   (>= $resultSize 1)))

(= (strategyMergeCullPressureTest)
   (let* (
     ($result (runMoses
                2
                (mkCscore 5.0 5 1.43 0.0 3.57)
                2
                (strategyMetaPop)
                0 2
                (5 random-player 3.5)
                hillClimbing
                30 2 1 1.0
                2 0.004 1000))
     ($resultSize (eval (OS.length $result))))
   (<= $resultSize 2)))

;; Convenience aggregate used by the shell harness for a cheap in-MeTTa all-run.
;; It returns a tuple so failures are easy to localize in PeTTa output.
(= (strategyAllUnitTests)
   ((strategyExpandSingleDemeTest)
    (strategyExpandMultiDemeTest)
    (strategyRunSingleGenerationTest)
    (strategyRunMaxCandidateCapTest)
    (strategyGameContextScoringTest)
    (strategyRunMultiGenerationMultiDemeTest)
    (strategyRunEmptySeedTest)
    (strategyMergeCullPressureTest)))

;; ---- State-capture case functions. Same proven invocation shape as the
;; ---- metta unit tests: runMoses inside a function-equation body, size out.
(= (strategyStateSingle)
   (let* (($result (runMoses 1 (mkCscore 5.0 5 1.43 0.0 3.57) 3 (strategyMetaPop)
                             0 1 (5 random-player 3.5) hillClimbing
                             30 5 2 1.0 5 0.004 1000))
          ($size (eval (OS.length $result))))
     $size))

(= (strategyStateMultigenMultideme)
   (let* (($result (runMoses 3 (mkCscore 5.0 5 1.43 0.0 3.57) 3 (strategyMetaPop)
                             0 2 (5 random-player 3.5) hillClimbing
                             30 5 2 1.0 5 0.004 1000))
          ($size (eval (OS.length $result))))
     $size))

(= (strategyStateEmptySeed)
   (let* (($result (runMoses 2 (mkCscore 10.0 0 0 0.0 10) 3 (emptyStrategyMetaPop)
                             0 2 (10 random-player 3.5) hillClimbing
                             30 5 2 1.0 5 0.004 1000))
          ($size (eval (OS.length $result))))
     $size))

(= (strategyStateMergeCullSmoke)
   (let* (($result (runMoses 2 (mkCscore 5.0 5 1.43 0.0 3.57) 2 (strategyMetaPop)
                             0 2 (5 random-player 3.5) hillClimbing
                             30 5 2 1.0 2 0.004 1000))
          ($size (eval (OS.length $result))))
     $size))

(= (strategyStateMergeCullPressure)
   (let* (($result (runMoses 2 (mkCscore 5.0 5 1.43 0.0 3.57) 2 (strategyMetaPop)
                             0 2 (5 random-player 3.5) hillClimbing
                             30 2 1 1.0 2 0.004 1000))
          ($size (eval (OS.length $result))))
     $size))

;; Empty-seed lineage pressure case.  Starts from a bare PRIORITIZED-OR and an
;; unreachable max score so all 5 generations run, exercising multi-generation
;; strategy state/action emission and lineage fields without relying on a
;; particular search depth.  The current sampler can reach strong move programs
;; in the first expansion and then retain them across later generations.
(= (strategyStateDeepLineage)
   (let* (($result (runMoses 5 (mkCscore 100.0 0 0 0.0 100) 5 (emptyStrategyMetaPop)
                             0 2 (20 random-player 3.5) hillClimbing
                             500 5 2 1.0 5 0.004 1000))
          ($size (eval (OS.length $result))))
     $size))

;; -------------------------------------------------------------------------
;; Shell harness result wrappers (run_strategy_smoke_test.sh).
;; -------------------------------------------------------------------------

(= (strategy-metta-result $case $ok)
   (if $ok (strategy-metta PASS $case) (strategy-metta FAIL $case)))

(= (strategy-state-result-size $case $size)
   (strategy-state $case $size))
