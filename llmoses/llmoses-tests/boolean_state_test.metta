;; llmoses/llmoses-tests/boolean_state_test.metta
;;
;; Targeted boolean LLMOSES smoke + pressure tests (NOT classic demo problems).
;; Uses the same XOR fixture stack as expand-demes-test; run via:
;;   ./run_boolean_smoke_test.sh metta|state <case|all>
;;
;; Classic MOSES demos (pa, dj, maj, mux, …) live in demos_test.metta and
;; are run via ./run_moses_demo.sh demo <key>.

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
!(import! &self llmoses/deme/expand-deme)

;; Fixtures copied from expand-demes-test (XOR 3-var table).
(= (table1) (eval (createTruthTableBScore 2 (mkITable
                         (Cons (Cons False (Cons False (Cons False Nil)))
                         (Cons (Cons True  (Cons False (Cons False Nil)))
                         (Cons (Cons False (Cons True  (Cons False Nil)))
                         (Cons (Cons True  (Cons True  (Cons True  Nil))) Nil))))
                         (Cons A (Cons B (Cons O Nil)))))))

(= (ttable1) (mkITable
                         (Cons (Cons False (Cons False (Cons False Nil)))
                         (Cons (Cons True  (Cons False (Cons False Nil)))
                         (Cons (Cons False (Cons True  (Cons False Nil)))
                         (Cons (Cons True  (Cons True  (Cons True  Nil))) Nil))))
                         (Cons A (Cons B (Cons O Nil)))))

(= (metaPop2) (ConsOS (mkExemplar (mkTree (mkNode AND) Nil) (mkDemeId "1")
                      (mkCscore -4 2 1.0 0.0 -4.0)
                      (mkBScore (Cons -1 (Cons -1 (Cons -1 (Cons -1 Nil)))))) NilOS))

(= (booleanTargetCscore) (mkCscore -0.1 2 0.1 0.1 3))
(= (booleanTestContext) (False sim (table1) (ttable1)))

;; ---- MeTTa unit smoke (no JSON schema) ------------------------------------
(= (booleanRunSingleGenerationTest)
   (let* (($result (runMoses 1 (booleanTargetCscore) 3 (metaPop2) 0 1
                             (booleanTestContext) hillClimbing
                             5 2 0 1 3 0.004 1000))
          ($size (eval (OS.length $result))))
     (>= $size 1)))

(= (booleanRunMultiGenerationTest)
   (let* (($result (runMoses 2 (booleanTargetCscore) 3 (metaPop2) 0 2
                             (booleanTestContext) hillClimbing
                             5 2 0 1 3 0.004 1000))
          ($size (eval (OS.length $result))))
     (>= $size 1)))

(= (booleanMergeCullPressureTest)
   (let* (($result (runMoses 2 (booleanTargetCscore) 2 (metaPop2) 0 2
                             (booleanTestContext) hillClimbing
                             5 2 1 1.0 2 0.004 1000))
          ($size (eval (OS.length $result))))
     (<= $size 2)))

;; ---- State/action JSON capture (same run shapes, size out) -----------------
(= (booleanStateSingle)
   (let* (($result (runMoses 1 (booleanTargetCscore) 3 (metaPop2) 0 1
                             (booleanTestContext) hillClimbing
                             5 2 0 1 3 0.004 1000))
          ($size (eval (OS.length $result))))
     $size))

(= (booleanStateMultigenMultideme)
   (let* (($result (runMoses 3 (booleanTargetCscore) 3 (metaPop2) 0 2
                             (booleanTestContext) hillClimbing
                             5 2 0 1 3 0.004 1000))
          ($size (eval (OS.length $result))))
     $size))

(= (booleanStateMergeCullSmoke)
   (let* (($result (runMoses 2 (booleanTargetCscore) 2 (metaPop2) 0 2
                             (booleanTestContext) hillClimbing
                             5 2 0 1 2 0.004 1000))
          ($size (eval (OS.length $result))))
     $size))

(= (booleanStateMergeCullPressure)
   (let* (($result (runMoses 2 (booleanTargetCscore) 2 (metaPop2) 0 2
                             (booleanTestContext) hillClimbing
                             5 2 1 1.0 2 0.004 1000))
          ($size (eval (OS.length $result))))
     $size))

;; Shell harness wrappers (run_boolean_smoke_test.sh).
(= (boolean-metta-result $case $ok)
   (if $ok (boolean-metta PASS $case) (boolean-metta FAIL $case)))

(= (boolean-state-result-size $case $size)
   (boolean-state $case $size))
