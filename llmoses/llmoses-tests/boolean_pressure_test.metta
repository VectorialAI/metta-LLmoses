;; llmoses/llmoses-tests/boolean_pressure_test.metta
;;
;; Slow / heavy boolean regression cases moved from the old run_moses_demo harness.
;; Run via: ./run_boolean_smoke_test.sh metta|state <case>
;;
;; Classic demos (pa, dj, …) are NOT here — use ./run_moses_demo.sh demo <key>.

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
!(import! &self moses/demo-problems)

(= (mapG $f NilOS) NilOS)
(= (mapG $f Nil) Nil)
(= (mapG $f ($ctor $x $xs)) ($ctor ($f $x) (mapG $f $xs)))
(= (printExemplar (mkExemplar $tree $demeId $cscore $bscore))
   (println! (Tree: (preOrder $tree) CScore: $cscore Bscore: $bscore)))

;; Seed metapop: AND with worst score; bscore length 8 matches parity-3 table.
(= (parity3MetaPop)
   (ConsOS
     (mkExemplar
       (mkTree (mkNode AND) Nil)
       (mkDemeId "1")
       (mkCscore -8 2 1.0 0.0 -8.0)
       (mkBScore (Cons -1 (Cons -1 (Cons -1 (Cons -1 (Cons -1 (Cons -1 (Cons -1 (Cons -1 Nil))))))))))
     NilOS))

(= (parity3TargetCscore) (mkCscore 0 3 1.0 0.0 0))

(= (parity3Context)
   (let* (($ttbs (eval (createTruthTableBScore 2 (parity3)))))
     (False None $ttbs (parity3))))

;; Full 15-gen parity-3 pressure run (former run_moses_demo.sh parity3).
(= (booleanPressureParity3)
   (let* (($result (runMoses
                     15 (parity3TargetCscore) 6 (parity3MetaPop) 0 3
                     (parity3Context) hillClimbing
                     100 10 2 1 6 0.004 1000))
          ($size (eval (OS.length $result))))
     (>= $size 1)))

;; Shorter parity-3 run for state/action JSON schema validation.
(= (booleanStateParity3Short)
   (let* (($result (runMoses
                     3 (parity3TargetCscore) 6 (parity3MetaPop) 0 3
                     (parity3Context) hillClimbing
                     100 10 2 1 6 0.004 1000))
          ($size (eval (OS.length $result))))
     $size))

;; SMD representation multiplicity pressure (former crep-smd).
(= (booleanPressureCrepSmd)
   (let* (($r3 (collapse (representation 3 (mkTree (mkNode AND) Nil) (parity3) smd False () mi)))
          ($r1 (collapse (representation 1 (mkTree (mkNode AND) Nil) (parity3) smd False () mi)))
          ($n3 (size-atom $r3))
          ($n1 (size-atom $r1)))
     (and (> $n3 0) (> $n1 0))))

(= (boolean-pressure-result $case $ok)
   (if $ok (boolean-pressure PASS $case) (boolean-pressure FAIL $case)))

(= (boolean-pressure-state-size $case $size)
   (boolean-pressure-state $case $size))
