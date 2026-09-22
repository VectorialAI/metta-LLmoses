;; LLMOSES similarity-scorers regression.
;; Purpose: pin the union-free jaccardIndex (U-001 workaround) and the builtins
;; it depends on. Every probe is an assertion; a bare expression that "looks
;; right" in a log is not a test.
;;
;; Run via:   ./run_boolean_smoke_test.sh metta similarity-scorers

!(import! &self utilities/general-helpers)
!(import! &self llmoses/utilities/general-helpers)  ;; LLMOSES override: adds first, first-from-pair, second-from-pair
!(import! &self utilities/list-methods)
!(import! &self feature-selection/feature-selection-helpers)
!(import! &self llmoses/feature-selection/similarity-scorers)

;; ── builtins the formula depends on ────────────────────────────────────────
!(assertEqual (intersection-atom (1 2) (2 3)) (2))
!(assertEqual (size-atom (1 2 3)) 3)
!(assertEqual (size-atom ()) 0)

;; ── float-division canary: integer truncation would zero every score ───────
!(assertEqual (> (/ 1 3) 0.3) True)
!(assertEqual (< (/ 1 3) 0.34) True)

;; ── jaccardIndex = |A∩B| / (|A| + |B| − |A∩B|) ─────────────────────────────
!(assertEqual (jaccardIndex (1 2) (2 3)) (/ 1 3))     ;; 1/(2+2-1)
!(assertEqual (jaccardIndex (A B) (B A)) 1)           ;; identical sets, order-free
!(assertEqual (jaccardIndex (A) (B)) 0)               ;; disjoint
!(assertEqual (jaccardIndex (0 1 2 3) (1 2 3 4)) 0.6) ;; width > 2 (U-001 regression)
!(assertEqual (jaccardIndex (1 2 3) (3)) (/ 1 3))     ;; asymmetric sizes
!(assertEqual (jaccardIndex (1 2 3) (1 2 3 4 5 6)) 0.5)

;; ── pair accessors used by smd.metta and the helpers ───────────────────────
!(assertEqual (first  (10 (1 2))) 10)
!(assertEqual (second (10 (1 2))) (1 2))
!(assertEqual (first-from-pair  (10 (1 2))) 10)
!(assertEqual (second-from-pair (10 (1 2))) (1 2))
!(assertEqual (first  (second (1 (10 (1 2))))) 10)
!(println! "similarity-scorers: PASS")
