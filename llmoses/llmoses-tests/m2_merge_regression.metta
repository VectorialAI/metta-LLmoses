;; Regression fixtures written before the F-022 fix. Run from repository root.
!(import! &self utilities/general-helpers)
!(import! &self utilities/list-methods)
!(import! &self utilities/ordered-set)
!(import! &self llmoses/scoring/cscore)
!(import! &self llmoses/metapopulation/metapopulation)
!(import! &self llmoses/deme/merge-demes)
!(import! &self llmoses/feature-selection/similarity-scorers)
!(import! &self "state_builder.py")

(= (m2A) (mkExemplar A a (mkCscore -2 1 0 0 -2)
                       (mkBScore (cons -1 (cons 0 (cons -1 ()))))))
(= (m2B) (mkExemplar B b (mkCscore -2 1 0 0 -2)
                       (mkBScore (cons 0 (cons -1 (cons -1 ()))))))
(= (m2C) (mkExemplar C c (mkCscore -1 1 0 0 -1)
                       (mkBScore (cons -1 (cons 0 (cons 0 ()))))))
;; A and B incomparable; C dominates A; B must survive the pivot restart.
!(assertEqual (removeDominated (cons (m2A) (cons (m2B) (cons (m2C) ()))))
              (cons (m2C) (cons (m2B) ())))
;; Equal score is not element identity. Equal tree is, regardless of deme ID.
!(assertEqual (compareExemplar (m2A) (m2B)) G)
!(assertEqual (compareExemplar (m2A)
                (mkExemplar A other (mkCscore -2 1 0 0 -2)
                  (mkBScore (cons -1 (cons 0 (cons -1 ())))))) E)
!(assertEqual (OS.length (OS.insert compareExemplar (m2B)
                          (cons (m2A) ()))) 2)
;; U-006 / D-DUPSLOT: the native E contract is restored -- an equal tree under
;; a different deme id is the same element and OS.insert must skip it, not
;; append a duplicate slot.
!(assertEqual (OS.length (OS.insert compareExemplar
                (mkExemplar A other (mkCscore -2 1 0 0 -2)
                  (mkBScore (cons -1 (cons 0 (cons -1 ())))))
                (cons (m2A) ()))) 1)
;; U-001/Jaccard: feature sets wider than parity two; no buggy native unify.
!(assertEqual (jaccardIndex (0 1 2 3) (1 2 3 4)) 0.6)
;; Complexity coefficient through the MeTTa bridge (reversal #20): the legacy
;; ratio 3.5 preserves the native default; ratio 0 clamps to the balanced
;; ceiling 1.0 rather than native's off switch. Direct coef = 0 zeroes the
;; complexity penalty so penalized == raw (cscore.metta multiplies).
!(assertEqual (and (< (- (getComplexityCoef 3.5) 0.2857) 0.0001)
                   (> (- (getComplexityCoef 3.5) 0.2857) -0.0001)) True)
!(assertEqual (== (getComplexityCoef 0) 1.0) True)
!(assertEqual (== (getComplexityCoef -2) 1.0) True)
;; PeTTa's == compares terms: integer -3 and float -3.0 are distinct. Check
;; exact numeric equality (both bounds), without rounding the production score.
!(assertEqual
   (let $score (getPenScore (updatePenalizedScore (mkCscore -3 4 (* 4 0) 0.0 0) False))
        (and (>= $score -3) (<= $score -3))) True)
!(println! "m2-merge-regression: PASS")
