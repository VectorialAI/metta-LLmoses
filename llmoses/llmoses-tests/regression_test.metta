;; regression_test.metta — focused regression (contin) MOSES tests.
;;
;; This file intentionally defines callable test forms instead of running every
;; assertion at import time. The companion run_regression_state_test.sh harness
;; imports this file and invokes one named test or all tests.
;;
;; Install location expected by the harness:
;;   llmoses/llmoses-tests/regression_test.metta
;;
;; Forked imports (replace the upstream versions):
;;   llmoses/representation/knob-representation      (mkCSK accessors)
;;   llmoses/optimization/hill-climbing-helpers        (regression dispatch + epsilon)
;; New regression modules:
;;   llmoses/scoring/numeric-eval, llmoses/scoring/regression-bscore,
;;   llmoses/representation/build-contin
;;
;; Classic demo coverage in this harness:
;;   sr     — simpleRegression (contin path)
;;   cp     — cpDemoTable / majority3 combo-program recovery (boolean path)
;;   ann-cp — same cp target; ANN scoring not yet ported (boolean smoke)

!(import! &self utilities/general-helpers)
!(import! &self moses/demo-problems)
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
!(import! &self llmoses/scoring/bscore)
!(import! &self llmoses/scoring/cscore)
!(import! &self llmoses/scoring/complexity-based-scorer)
!(import! &self llmoses/scoring/numeric-eval)
!(import! &self llmoses/scoring/regression-bscore)
!(import! &self feature-selection/feature-selection-helpers)
!(import! &self llmoses/feature-selection/similarity-scorers)
!(import! &self llmoses/feature-selection/select-top-features)
!(import! &self feature-selection/simple)
!(import! &self feature-selection/smd)
!(import! &self feature-selection/incremental)
!(import! &self feature-selection/hc)
!(import! &self feature-selection/random-feature-selection)
!(import! &self feature-selection/feature-selection-main)
!(import! &self llmoses/representation/knob-representation)
!(import! &self representation/lsk)
!(import! &self representation/logical-probe)
!(import! &self representation/logical-canonize)
!(import! &self representation/sample-logical-perms)
!(import! &self representation/add-logical-knobs)
!(import! &self representation/build-logical)
!(import! &self representation/build-knobs)
!(import! &self representation/knob-mapper)
!(import! &self representation/representation)
!(import! &self llmoses/representation/build-contin)
!(import! &self llmoses/representation/create-representation)
!(import! &self representation/instance)
!(import! &self llmoses/wrapper/extractors)
!(import! &self optimization/hillclimbing/cross-top-one-helpers)
!(import! &self optimization/hillclimbing/cross-top-one)
!(import! &self llmoses/optimization/hill-climbing-helpers)
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

;; -------------------------------------------------------------------------
;; Fixtures — numeric tables (last column is the regression target).
;; sr demo (simpleRegression) lives in moses/demo-problems.metta.
;; -------------------------------------------------------------------------

;; y = 2x + 1 — alias of the sr demo table for backward-compatible fixtures.
(= (lineTable) (simpleRegression))

;; y = x1 + 2*x2 + 3 over six rows.
(= (multiFeatTable)
   (mkITable
     (Cons (Cons 0 (Cons 0 (Cons 3 Nil)))
     (Cons (Cons 1 (Cons 0 (Cons 4 Nil)))
     (Cons (Cons 0 (Cons 1 (Cons 5 Nil)))
     (Cons (Cons 1 (Cons 1 (Cons 6 Nil)))
     (Cons (Cons 2 (Cons 1 (Cons 7 Nil)))
     (Cons (Cons 1 (Cons 2 (Cons 8 Nil)) ) Nil))))))
     (Cons X1 (Cons X2 (Cons Y Nil)))))

;; y = 0.5*x — the decoder-refinement target (coefficient 0.5 requires the
;; Right-then-Left reversal/halving tail of the trit walk).
(= (fracTable)
   (mkITable
     (Cons (Cons 0 (Cons 0 Nil))
     (Cons (Cons 1 (Cons 0.5 Nil))
     (Cons (Cons 2 (Cons 1.0 Nil))
     (Cons (Cons 3 (Cons 1.5 Nil))
     (Cons (Cons 4 (Cons 2.0 Nil)) Nil)))))
     (Cons X (Cons Y Nil))))

;; y = x1 + x2 + x3 — arity 3; with depth 4 this yields (3+1)*4 = 16 trit
;; knobs, large enough that distance >= 2 forces the random sampling path.
(= (samplingTable)
   (mkITable
     (Cons (Cons 0 (Cons 0 (Cons 0 (Cons 0 Nil))))
     (Cons (Cons 1 (Cons 0 (Cons 0 (Cons 1 Nil))))
     (Cons (Cons 0 (Cons 1 (Cons 1 (Cons 2 Nil))))
     (Cons (Cons 1 (Cons 1 (Cons 1 (Cons 3 Nil))))
     (Cons (Cons 2 (Cons 1 (Cons 2 (Cons 5 Nil)))) Nil)))))
     (Cons X1 (Cons X2 (Cons X3 (Cons Y Nil))))))

;; -------------------------------------------------------------------------
;; Fixtures — trees and metapops.
;; -------------------------------------------------------------------------

;; Exact tree for lineTable: (+ 1 (* 2 X)).
(= (exactLineTree) (buildLinearTree (Cons 1 (Cons 2 Nil)) (Cons X Nil)))

;; Imperfect seed: (+ 0 (* 1 X)) — bscore on lineTable is (-1 -4 -9 -16).
(= (seedLineTree) (buildLinearTree (Cons 0 (Cons 1 Nil)) (Cons X Nil)))

;; Seeded imperfect metapop (raw -30, complexity 3, ratio 3.5 penalty 0.857).
(= (regressionMetaPop)
   (ConsOS
     (mkExemplar
       (seedLineTree)
       (mkDemeId "0")
       (mkCscore -30.0 3 0.857 0.0 -30.857)
       (mkBScore (Cons -1 (Cons -4 (Cons -9 (Cons -16 Nil))))))
     NilOS))

;; Exact-fit metapop: raw score 0 must hit the bestPossibleScore termination.
(= (exactLineMetaPop)
   (ConsOS
     (mkExemplar
       (exactLineTree)
       (mkDemeId "0")
       (mkCscore 0.0 3 0.857 0.0 -0.857)
       (mkBScore (Cons 0 (Cons 0 (Cons 0 (Cons 0 Nil))))))
     NilOS))

;; Bare (+) exemplar with worst CScore — the asmoses contin exemplar seed is
;; id::plus. All knob means extract to 0.
(= (emptyRegressionMetaPop)
   (ConsOS
     (mkExemplar
       (mkTree (mkNode +) Nil)
       (mkDemeId "0")
       (eval (worstCscore))
       (mkBScore (Cons -10000.0 (Cons -10000.0 (Cons -10000.0 (Cons -10000.0 Nil))))))
     NilOS))

;; Imperfect multi-feature seed: (+ 0 (* 1 X1) (* 1 X2)).
(= (multiFeatSeedTree)
   (buildLinearTree (Cons 0 (Cons 1 (Cons 1 Nil))) (Cons X1 (Cons X2 Nil))))

(= (multiFeatMetaPop)
   (ConsOS
     (mkExemplar
       (multiFeatSeedTree)
       (mkDemeId "0")
       (mkCscore -60.0 5 1.428 0.0 -61.428)
       (mkBScore (Cons -9 (Cons -9 (Cons -16 (Cons -16 (Cons -16 (Cons -25 Nil))))))))
     NilOS))

;; Fractional seed: (+ 0 (* 0 X)) — raw -7.5 on fracTable.
(= (fracSeedTree) (buildLinearTree (Cons 0 (Cons 0 Nil)) (Cons X Nil)))
(= (fracMetaPop)
   (ConsOS
     (mkExemplar
       (fracSeedTree)
       (mkDemeId "0")
       (mkCscore -7.5 3 0.857 0.0 -8.357)
       (mkBScore (Cons 0 (Cons -0.25 (Cons -1.0 (Cons -2.25 (Cons -4.0 Nil)))))))
     NilOS))

;; Sampling seed: bare (+) over the arity-3 table.
(= (samplingMetaPop)
   (ConsOS
     (mkExemplar
       (mkTree (mkNode +) Nil)
       (mkDemeId "0")
       (eval (worstCscore))
       (mkBScore (Cons -10000.0 (Cons -10000.0 (Cons -10000.0 (Cons -10000.0 (Cons -10000.0 Nil)))))))
     NilOS))

;; Unreachable target Cscore — regression raw scores are always <= 0, so a
;; positive raw/penalized target can never structurally equal the top score.
(= (unreachableRegressionScore) (mkCscore 1.0 0 0.0 0.0 1.0))

;; Helpers for optional human-readable diagnostics.
(= (printExemplar (mkExemplar $tree $demeId $cscore $bscore))
   (println! (Tree: (preOrder $tree) CScore: $cscore Bscore: $bscore)))

;; -------------------------------------------------------------------------
;; Unit tier — regression-specific arithmetic with no boolean/strategy analog.
;; These run first and cheap (no MOSES loop).
;; -------------------------------------------------------------------------

;; Trit-walk decoder asserts from the verified contin_stepper table
;; (mean 0, step 1.0, expansion 2.0):
;;   all-Stop -> 0 (mean) ; R -> 1 ; RR -> 3 ; RRL -> 2 ;
;;   R L -> 0.5 (the discriminating reversal case the Appendix-B prose gets
;;   wrong) ; post-Stop trits ignored (R Stop R == R) ; L -> -1.
(= (continDecoderUnitTest)
   (== ((decodeContinTrits 0 1.0 2.0 (Cons 0 (Cons 0 (Cons 0 Nil))))
        (decodeContinTrits 0 1.0 2.0 (Cons 2 Nil))
        (decodeContinTrits 0 1.0 2.0 (Cons 2 (Cons 2 Nil)))
        (decodeContinTrits 0 1.0 2.0 (Cons 2 (Cons 2 (Cons 1 Nil))))
        (decodeContinTrits 0 1.0 2.0 (Cons 2 (Cons 1 Nil)))
        (decodeContinTrits 0 1.0 2.0 (Cons 2 (Cons 0 (Cons 2 Nil))))
        (decodeContinTrits 0 1.0 2.0 (Cons 1 Nil)))
       (0 1.0 3.0 2.0 0.5 1.0 -1.0)))

;; Hand trees against hand rows; floats through PeTTa marshalling.
;; (+ 1 (* 2 X)) at X=0 -> 1 ; X=3 -> 7. (+ 0.5 (* 0.5 X)) at X=3 -> 2.0.
(= (numericEvalUnitTest)
   (let* (
     ($expr (preOrder (exactLineTree)))
     ($fracExpr (preOrder (buildLinearTree (Cons 0.5 (Cons 0.5 Nil)) (Cons X Nil))))
     ($v0 (evalNumeric $expr (Cons (X 0) Nil)))
     ($v3 (evalNumeric $expr (Cons (X 3) Nil)))
     ($vf (evalNumeric $fracExpr (Cons (X 3) Nil)))
   )
   (== ($v0 $v3 $vf) (1 7 2.0))))

;; Exact tree -> bscore all zeros; wrong tree -> known negative values.
(= (regressionBscoreUnitTest)
   (let* (
     ($exact (scoreTreeRegression (lineTable) (exactLineTree) &regressionScoreCache))
     ($wrong (scoreTreeRegression (lineTable) (seedLineTree) &regressionScoreCache))
   )
   (and (== $exact (mkBScore (Cons 0 (Cons 0 (Cons 0 (Cons 0 Nil))))))
        (== $wrong (mkBScore (Cons -1 (Cons -4 (Cons -9 (Cons -16 Nil)))))))))

;; Knob build over the 1-feature lineTable: (1+1) groups x continDepth trit
;; knobs, multiplicity 3, CSK tag, correct contin metadata, and the all-Stop
;; instance decodes back to the seed tree (means).
(= (continKnobBuildTest)
   (let* (
     ($rep (continRepresentation (seedLineTree) (lineTable)))
     ($knobs (knobsOfRep $rep))
     ($n (List.length $knobs))
     ($k0 (List.head $knobs))
     ($depth (continDepth))
     ($allStop (mkInst (List.repeat $n 0)))
     ($cand (getContinCandidate $rep $allStop))
   )
   (== ($n (knobTag $k0) (getKnobMultip $k0) (knobContin $k0) (== $cand (seedLineTree)))
       ((* 2 $depth) CSK (mkMultip 3) (0 0 1.0 2.0 $depth) True))))

;; Score a fixed instance through transform with the tagged regression context
;; and assert the raw score matches scoreTreeRegression's sum. Guards the two
;; silent-misroute traps (boolean mkITable capture and strategy catch-all).
(= (transformDispatchTest)
   (let* (
     ($rep (continRepresentation (seedLineTree) (lineTable)))
     ($bscorer (createRegressionBScore 3.5 (lineTable)))
     ($n (List.length (knobsOfRep $rep)))
     ($inst (mkInst (List.repeat $n 0)))
     ($sInstSet (mkSInstSet (Cons (initInstScore $inst) Nil)))
     ((mkSInstSet $scored) (transform $sInstSet $rep $bscorer 3.5))
     ($cscore (getSInstScore (List.head $scored)))
     ($raw (getScore $cscore))
   )
   (== $raw -30)))

;; Convenience aggregate for a cheap in-MeTTa unit-tier run.
(= (regressionAllUnitTierTests)
   ((continDecoderUnitTest)
    (numericEvalUnitTest)
    (regressionBscoreUnitTest)
    (continKnobBuildTest)
    (transformDispatchTest)))

;; -------------------------------------------------------------------------
;; End-to-end MeTTa cases. These mirror the strategy expand/run tests but
;; target the regression overloads and stress the contin-specific dimensions:
;; trit neighborhoods, continuous-score merge comparators, decoder refinement,
;; random-sampling pressure, exact-fit termination, multigen recentering.
;; -------------------------------------------------------------------------

(= (regressionExpandSingleDemeTest)
   (let* (
     ($optimizedDemes (expandDeme
                        (regressionMetaPop)
                        0 1
                        (createRegressionBScore 3.5 (lineTable))
                        (lineTable)
                        hillClimbing))
     ($demeCount (size-atom $optimizedDemes)))
   (>= $demeCount 1)))

(= (regressionExpandMultiDemeTest)
   (let* (
     ($optimizedDemes (expandDeme
                        (regressionMetaPop)
                        0 2
                        (createRegressionBScore 3.5 (lineTable))
                        (lineTable)
                        hillClimbing))
     ($demeCount (size-atom $optimizedDemes)))
   (>= $demeCount 2)))

(= (regressionRunSingleGenerationTest)
   (let* (
     ($context ((createRegressionBScore 3.5 (lineTable)) (lineTable)))
     ($result (runMoses
                1
                (unreachableRegressionScore)
                3
                (regressionMetaPop)
                0 1
                $context
                hillClimbing
                30 5 2 1.0
                5 0.004 1000))
     ($resultSize (eval (OS.length $result))))
   (>= $resultSize 1)))

;; Seeded exact tree: raw score 0 must hit the bestPossibleScore termination
;; path inside hillClimbing (regression analog of boolean's known-XOR check);
;; the top candidate keeps a near-zero penalized score (only the constant
;; complexity penalty 3/3.5 below zero).
(= (regressionExactFitTerminationTest)
   (let* (
     ($context ((createRegressionBScore 3.5 (lineTable)) (lineTable)))
     ($result (runMoses
                1
                (unreachableRegressionScore)
                3
                (exactLineMetaPop)
                0 1
                $context
                hillClimbing
                30 5 2 1.0
                5 0.004 1000))
     ($top (eval (OS.getByIdx 0 $result)))
     ($pen (eval (getPenScore (getExemplarCscore $top)))))
   (> $pen -1.0)))

;; Flagship multigen run on lineTable (the parity3 analog): the top candidate's
;; penalized score must strictly improve on the seed's (-30.857). Not exact
;; recovery — robust to stochastic hill climbing.
(= (regressionLinearRecoveryTest)
   (let* (
     ($context ((createRegressionBScore 3.5 (lineTable)) (lineTable)))
     ($result (runMoses
                3
                (unreachableRegressionScore)
                3
                (regressionMetaPop)
                0 1
                $context
                hillClimbing
                30 5 2 1.0
                5 0.004 1000))
     ($top (eval (OS.getByIdx 0 $result)))
     ($pen (eval (getPenScore (getExemplarCscore $top)))))
   (> $pen -30.857)))

;; Multi-feature table: 3 coefficient knob groups (offset + 2 features) and an
;; improvement over the seed. Asserts the knob-group arithmetic via the rep.
(= (regressionMultiFeatureTest)
   (let* (
     ($rep (continRepresentation (multiFeatSeedTree) (multiFeatTable)))
     ($knobCount (List.length (knobsOfRep $rep)))
     ($context ((createRegressionBScore 3.5 (multiFeatTable)) (multiFeatTable)))
     ($result (runMoses
                2
                (unreachableRegressionScore)
                3
                (multiFeatMetaPop)
                0 1
                $context
                hillClimbing
                30 5 2 1.0
                5 0.004 1000))
     ($top (eval (OS.getByIdx 0 $result)))
     ($pen (eval (getPenScore (getExemplarCscore $top)))))
   (and (== $knobCount (* 3 (continDepth))) (> $pen -61.428))))

;; fracTable at depth >= 4: coefficient 0.5 requires the Left-after-Right
;; refinement (reversal/halving) steps and exercises the replaced improvement
;; threshold — fine refinements below 0.5 would silently plateau under the
;; old hard-coded epsilon.
(= (regressionFractionalRefinementTest)
   (let* (
     ($context ((createRegressionBScore 3.5 (fracTable)) (fracTable)))
     ($result (runMoses
                3
                (unreachableRegressionScore)
                3
                (fracMetaPop)
                0 1
                $context
                hillClimbing
                30 5 2 1.0
                5 0.004 1000))
     ($top (eval (OS.getByIdx 0 $result)))
     ($raw (eval (getScore (getExemplarCscore $top))))
     ($pen (eval (getPenScore (getExemplarCscore $top)))))
   (and (> $raw -3.0) (> $pen -8.357))))

;; Arity 3 at depth 4 -> 16 trit knobs; distance >= 2 forces the random
;; sampling path (the regression-specific stress; covers the updateInst
;; generalization that previously destructured mkLSK only).
(= (regressionSamplingPressureTest)
   (let* (
     ($context ((createRegressionBScore 3.5 (samplingTable)) (samplingTable)))
     ($result (runMoses
                2
                (unreachableRegressionScore)
                3
                (samplingMetaPop)
                0 1
                $context
                hillClimbing
                30 5 2 1.0
                5 0.004 1000))
     ($resultSize (eval (OS.length $result))))
   (>= $resultSize 1)))

;; Evolve from the bare (+) exemplar.
(= (regressionEmptySeedTest)
   (let* (
     ($context ((createRegressionBScore 3.5 (lineTable)) (lineTable)))
     ($result (runMoses
                2
                (unreachableRegressionScore)
                3
                (emptyRegressionMetaPop)
                0 2
                $context
                hillClimbing
                30 5 2 1.0
                5 0.004 1000))
     ($resultSize (eval (OS.length $result))))
   (>= $resultSize 1)))

;; Small nToKeep/maxCands: continuous float scores through the merge/cull
;; comparators (boolean scores were integer-valued — new comparator pressure).
(= (regressionMergeCullPressureTest)
   (let* (
     ($context ((createRegressionBScore 3.5 (lineTable)) (lineTable)))
     ($result (runMoses
                2
                (unreachableRegressionScore)
                2
                (regressionMetaPop)
                0 2
                $context
                hillClimbing
                30 2 1 1.0
                2 0.004 1000))
     ($resultSize (eval (OS.length $result))))
   (<= $resultSize 2)))

;; Combined multigen + multideme (the strategy-suite analog).
(= (regressionMultigenMultidemeTest)
   (let* (
     ($context ((createRegressionBScore 3.5 (lineTable)) (lineTable)))
     ($result (runMoses
                3
                (unreachableRegressionScore)
                3
                (regressionMetaPop)
                0 2
                $context
                hillClimbing
                30 5 2 1.0
                5 0.004 1000))
     ($resultSize (eval (OS.length $result))))
   (>= $resultSize 1)))

;; ---- State-capture case functions. Same proven invocation shape as the
;; ---- metta unit tests: runMoses inside a function-equation body, size out.
(= (regressionStateSingle)
   (let* (($context ((createRegressionBScore 3.5 (lineTable)) (lineTable)))
          ($result (runMoses 1 (unreachableRegressionScore) 3 (regressionMetaPop)
                             0 1 $context hillClimbing
                             30 5 2 1.0 5 0.004 1000))
          ($size (eval (OS.length $result))))
     $size))

(= (regressionStateMultigenMultideme)
   (let* (($context ((createRegressionBScore 3.5 (lineTable)) (lineTable)))
          ($result (runMoses 3 (unreachableRegressionScore) 3 (regressionMetaPop)
                             0 2 $context hillClimbing
                             30 5 2 1.0 5 0.004 1000))
          ($size (eval (OS.length $result))))
     $size))

(= (regressionStateEmptySeed)
   (let* (($context ((createRegressionBScore 3.5 (lineTable)) (lineTable)))
          ($result (runMoses 2 (unreachableRegressionScore) 3 (emptyRegressionMetaPop)
                             0 2 $context hillClimbing
                             30 5 2 1.0 5 0.004 1000))
          ($size (eval (OS.length $result))))
     $size))

;; Exact-fit state case — verifies state/terminal emission on the early
;; bestPossibleScore termination (new wrinkle vs strategy).
(= (regressionStateExactFit)
   (let* (($context ((createRegressionBScore 3.5 (lineTable)) (lineTable)))
          ($result (runMoses 1 (unreachableRegressionScore) 3 (exactLineMetaPop)
                             0 1 $context hillClimbing
                             30 5 2 1.0 5 0.004 1000))
          ($size (eval (OS.length $result))))
     $size))

(= (regressionStateMergeCullPressure)
   (let* (($context ((createRegressionBScore 3.5 (lineTable)) (lineTable)))
          ($result (runMoses 2 (unreachableRegressionScore) 2 (regressionMetaPop)
                             0 2 $context hillClimbing
                             30 2 1 1.0 2 0.004 1000))
          ($size (eval (OS.length $result))))
     $size))

;; Explicit sr demo smoke — confirms the named simpleRegression table drives
;; the contin regression path (not the ad-hoc lineTable-only fixtures).
(= (regressionSrDemoTest)
   (let* (
     ($table (simpleRegression))
     ($context ((createRegressionBScore 3.5 $table) $table))
     ($result (runMoses
                1
                (unreachableRegressionScore)
                3
                (regressionMetaPop)
                0 1
                $context
                hillClimbing
                30 5 2 1.0
                5 0.004 1000))
     ($resultSize (eval (OS.length $result))))
   (>= $resultSize 1)))

;; cp — learn a supplied Combo program: MOSES builds the truth table from the
;; target (majority3) and tries to recover it. Boolean runMoses overload.
(= (regressionCpDemoTest)
   (let* (
     ($problem (cpDemoTable))
     ($cpxPen 3.5)
     ($truthTableBScore (createTruthTableBScore $cpxPen $problem))
     (($ctor $worstPossibleBScore) (worstPossibleScore $truthTableBScore))
     ($worstPossibleScore (List.sum $worstPossibleBScore))
     ($bestPosssibleCscore (getBestPossibleCscore $cpxPen $problem))
     ($metaPop (ConsOS
                 (mkExemplar (mkTree (mkNode true) Nil) (mkDemeId "1")
                   (mkCscore $worstPossibleScore 0 $cpxPen 0 $worstPossibleScore)
                   ($ctor $worstPossibleBScore))
                 NilOS))
     ($result (runMoses 1 $bestPosssibleCscore 3 $metaPop 0 1
               False smd $truthTableBScore hillClimbing
               100 10 2 1 $problem 6 0.004 1000))
     ($resultSize (eval (OS.length $result)))
   )
   (>= $resultSize 1)))

;; ann-cp — ANN combo-program learning (classic -H ann-cp). Until ANN knob
;; representation lands, this exercises the same cp boolean recovery smoke.
(= (regressionAnnCpDemoTest)
   (let* (
     ($problem (demoProblem annCp))
     ($cpxPen 3.5)
     ($truthTableBScore (createTruthTableBScore $cpxPen $problem))
     (($ctor $worstPossibleBScore) (worstPossibleScore $truthTableBScore))
     ($worstPossibleScore (List.sum $worstPossibleBScore))
     ($bestPosssibleCscore (getBestPossibleCscore $cpxPen $problem))
     ($metaPop (ConsOS
                 (mkExemplar (mkTree (mkNode true) Nil) (mkDemeId "1")
                   (mkCscore $worstPossibleScore 0 $cpxPen 0 $worstPossibleScore)
                   ($ctor $worstPossibleBScore))
                 NilOS))
     ($result (runMoses 1 $bestPosssibleCscore 3 $metaPop 0 1
               False smd $truthTableBScore hillClimbing
               100 10 2 1 $problem 6 0.004 1000))
     ($resultSize (eval (OS.length $result)))
   )
   (>= $resultSize 1)))

;; -------------------------------------------------------------------------
;; Shell harness result wrappers (run_regression_state_test.sh).
;; -------------------------------------------------------------------------

(= (regression-metta-result $case $ok)
   (if $ok (regression-metta PASS $case) (regression-metta FAIL $case)))

(= (regression-state-result-size $case $size)
   (regression-state $case $size))
