;; LLMOSES additions to utilities/general-helpers.metta. Import right after
;; utilities/general-helpers, before feature-selection and representation modules.
;; Defines first, which upstream leaves commented out, and the pair accessors
;; first-from-pair / second-from-pair used by the feature-selection modules.

;; From a tuple (Pair) return the first element
;; (: first (-> ($a $b) $a))
(= (first ($a $b)) $a)

;; Named pair accessors with the same semantics as first/second.
(= (first-from-pair  ($a $b)) $a)
(= (second-from-pair ($a $b)) $b)
