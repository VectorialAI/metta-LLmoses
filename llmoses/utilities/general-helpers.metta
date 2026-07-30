;; LLMOSES override / extension of utilities/general-helpers.
;; Import this immediately after utilities/general-helpers so these definitions
;; are in scope before any feature-selection or representation modules are loaded.
;;
;; Changes vs. the base:
;;   - Uncomments (first ($a $b)) - needed by smd.metta, feature-selection-helpers,
;;     lsk.metta, and select-top-features.metta.  The base file leaves it commented
;;     out; this override adds it without touching the root file.
;;   - Adds first-from-pair / second-from-pair for contexts where the symbol names
;;     first/second could be ambiguous or shadowed.

;; From a tuple (Pair) return the first element
;; (: first (-> ($a $b) $a))
(= (first ($a $b)) $a)

;; Named pair accessors with the same semantics as first/second.
(= (first-from-pair  ($a $b)) $a)
(= (second-from-pair ($a $b)) $b)
