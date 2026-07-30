;; LLMOSES createRepresentation overlay.
;; Delegates to representation.metta so feature selection, pruning, enforced
;; features, and strategy representation stay in one builder. The caller handles
;; the returned representation list when feature selection is disabled.

;; createRepresentation -- calls on the representation building procedure
;; (: createRepresentation (-> Number (Tree $a) (ITable $a) Symbol Bool Expression Symbol Representation))
;; For games: createRepresentation($nDeme, $tree)
;; For boolean: createRepresentation($nDeme, $tree, $itable, $algo, $prune, $enforced, $scorer)

;; Game strategy representation (2 parameters)
;;(: createRepresentation (-> Number (Tree $a) (List Representation)))
(= (createRepresentation $nDeme $tree)
    (eval (representation $tree $nDeme)))

;; Boolean logic representation (7 parameters)
;; Pass the representation list through to treeNeighborhood; it peels the single
;; representation when feature selection is off.
(= (createRepresentation $nDeme $tree (mkITable $table $labels) $algo $prune-exemplar $enforced-fts $scorerType)
    (eval (representation $nDeme $tree (mkITable $table $labels) $algo $prune-exemplar $enforced-fts $scorerType)))
