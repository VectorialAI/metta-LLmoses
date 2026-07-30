;; LLMOSES similarity-scorers smoke test.
;; Purpose: confirm that the builtins jaccardIndex depends on are functional
;; and that float division is not truncated.
;;
;; Run via:   ./run_boolean_smoke_test.sh metta similarity-scorers
;;
;; Reading the results:
;;   • Any expression that reduces to ITSELF (unreduced atom) is the culprit.
;;   • !(/ 1 3) → 0 means integer truncation; all Jaccard scores would be 0.
;;   • !(jaccardIndex (1 2) (2 3)) → 0.333... confirms the full path is clean.

!(import! &self utilities/general-helpers)
!(import! &self llmoses/utilities/general-helpers)  ;; LLMOSES override: adds first, first-from-pair, second-from-pair
!(import! &self utilities/list-methods)
!(import! &self feature-selection/feature-selection-helpers)
!(import! &self llmoses/feature-selection/similarity-scorers)

;; ── PeTTa-proven builtins (ground truth — these MUST pass) ─────────────────
!(assertEqual (intersection-atom (1 2) (2 3)) (2))   ;; expect (2)
!(assertEqual (size-atom (1 2 3)) 3)                  ;; expect 3

;; ── Float-division canary ──────────────────────────────────────────────────
;; If this returns 0, all Jaccard scores are wrong (integer truncation).
!(/ 1 3)                                              ;; expect 0.333…

;; ── Union-side suspects (leave unreduced = broken) ─────────────────────────
!(union-atom (1 2) (2 3))                             ;; expect (1 2 3) or similar
!(list_to_set (1 2 2 3))                              ;; PRIME SUSPECT — may not exist
!(union-atom-set (1 2) (2 3))                         ;; fails if either above fails

;; ── Full jaccardIndex path through the LLMOSES formula ─────────────────────
!(assertEqual (jaccardIndex (1 2) (2 3)) (/ 1 3))     ;; 1/(2+2-1) = 1/3
!(assertEqual (jaccardIndex (A B) (B A)) 1)           ;; identical sets → 1
!(assertEqual (jaccardIndex (A) (B)) 0)               ;; disjoint → 0

;; ── first / second pair-accessor probes ────────────────────────────────────
;; first was commented out at general-helpers:706; the line is now live.
;; These four probes confirm both first/second and the named variants reduce.
;; Any result that comes back as the raw expression (unreduced) is a broken accessor.
!(assertEqual (first  (10 (1 2))) 10)              ;; first defined in general-helpers
!(assertEqual (second (10 (1 2))) (1 2))           ;; second was already live
!(assertEqual (first-from-pair  (10 (1 2))) 10)    ;; new named accessor
!(assertEqual (second-from-pair (10 (1 2))) (1 2)) ;; new named accessor

;; Nested access — mirrors the pattern in smd.metta line 56/61 and helpers:381
!(assertEqual (first  (second (1 (10 (1 2))))) 10) ;; (second ...) → (10 (1 2)), then first
