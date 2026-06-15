;; LLMOSES feature-selection pressure test — FS = smd, nDeme = 3.
;; Purpose: confirm that first/first-from-pair/second-from-pair are in scope,
;;          stochasticMaxDependency runs clean, and jaccardIndex fires correctly
;;          through the real rankFtSet → rankIterator path.
;;
;; Run via:   ./run_boolean_smoke_test.sh metta fs-smd
;;
;; Reading the results:
;;   • JDBG lines show the $last-ft / $current-ft values reaching jaccardIndex.
;;     If either is an unreduced atom the FS accessor chain is broken.
;;   • Any assertEqual that prints FAILED identifies the broken layer.

!(import! &self utilities/general-helpers)
!(import! &self llmoses/utilities/general-helpers)  ;; adds first, first-from-pair, second-from-pair
!(import! &self utilities/list-methods)
!(import! &self utilities/pair)
!(import! &self utilities/map)
!(import! &self utilities/ordered-multimap)
!(import! &self utilities/ordered-set)
!(import! &self utilities/ordered-multiset)
!(import! &self utilities/nodeId)
!(import! &self utilities/lazy-random-selector)
!(import! &self utilities/lru-cache)

!(import! &self scoring/cscore)                             ;; mkCscore needed by rankFtSet

!(import! &self feature-selection/feature-selection-helpers)
!(import! &self llmoses/feature-selection/similarity-scorers)       ;; LLMOSES fork: union-free jaccardIndex
!(import! &self llmoses/feature-selection/select-top-features)      ;; LLMOSES fork: JDBG print in rankIterator
!(import! &self feature-selection/simple)
!(import! &self feature-selection/smd)
!(import! &self feature-selection/incremental)
!(import! &self feature-selection/hc)
!(import! &self feature-selection/random-feature-selection)
!(import! &self feature-selection/feature-selection-main)

;; ── 4-input test table (same fixture as feature-selection/tests/smd-test.metta) ──
(= (fsp-table)
    (mkITable
        (Cons (Cons True  (Cons True  (Cons False (Cons True  (Cons True   Nil)))))
        (Cons (Cons True  (Cons False (Cons False (Cons True  (Cons True   Nil)))))
        (Cons (Cons False (Cons True  (Cons False (Cons True  (Cons False  Nil)))))
        (Cons (Cons False (Cons False (Cons False (Cons True  (Cons False  Nil))))) Nil))))
        (Cons A (Cons B (Cons C (Cons D (Cons Output Nil)))))))

;; ── Layer 1: first / second / first-from-pair / second-from-pair ────────────
!(assertEqual (first  (10 (1 2))) 10)
!(assertEqual (second (10 (1 2))) (1 2))
!(assertEqual (first-from-pair  (10 (1 2))) 10)
!(assertEqual (second-from-pair (10 (1 2))) (1 2))

;; ── Layer 2: stochasticMaxDependency — the smd FS algo ──────────────────────
;; Returns a list of (score feature-indices) pairs; check we get the right count.
!(assertEqual
    (let $res (stochasticMaxDependency 0 3 3 (fsp-table) mi ())
        (size-atom $res))
    3)

!(assertEqual
    (let $res (stochasticMaxDependency 0 2 3 (fsp-table) mi ())
        (size-atom $res))
    3)

;; ── Layer 3: selectTopFts with ja scorer and nDeme = 3 ──────────────────────
;; Pre-computed smd-style input: 3 feature sets with scores.
;; JDBG lines from rankIterator will appear in the output — that is expected.
!(assertEqual
    (let $res (selectTopFts (fsp-table) 2 -1 False ja
                  ((1 (0 2)) (0.4 (3 1)) (0.3 (1 2 3)))
                  3)
        (size-atom $res))
    3)

;; nDeme = 3 capped by 3 available sets — all 3 should come back
!(assertEqual
    (let $res (selectTopFts (fsp-table) -2 -1 False ja
                  ((1 (0 2)) (0.4 (3 1)) (0.3 (1 2 3)))
                  3)
        (size-atom $res))
    3)

;; ── Layer 4: smd → selectTopFts pipeline (nDeme = 3, ja diversity) ──────────
;; Runs the real smd algo then pipes results through selectTopFts with ja.
;; This is the path exercised during a runMoses call with fs-algo = smd, nDeme = 3.
!(let*
    (($raw-sets (stochasticMaxDependency 0 2 3 (fsp-table) mi ()))
     ($top3     (selectTopFts (fsp-table) 2 -1 False ja $raw-sets 3))
     ($n        (size-atom $top3)))
    (println! (smd-ja-nDeme3 selected= $n sets= $top3)))
