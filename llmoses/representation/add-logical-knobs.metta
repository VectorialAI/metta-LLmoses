;; ============================================================================
;; llmoses/representation/add-logical-knobs.metta
;;
;; Drop-in replacement for representation/add-logical-knobs.metta — do NOT
;; import the upstream file (D-FSFORK: one copy per function, ever).
;;
;; D-033: the only change from the base file is that the target node's id is
;; destructured to its raw tree path and threaded into the perm samplers, so
;; the atom-prior draw site knows its position (operator + depth) and the
;; contextual lever_weights can condition combination weights. Everything
;; else is byte-equivalent base behavior.
;; ============================================================================

;; All available game moves
(= (getAllGameMoves) (playcenter playblock playwin playcorner playside))

;; helper function to the addLogicalKnobs
;; takes a tuple of knobs and return a tuple of knob and knobSpec pairs
;; (: pairKnobWithSpec (-> Expression Expression))
(= (pairKnobWithSpec $tuple)   (map-atom $tuple $knob ( (getKnobSpec $knob) $knob) ))

;; addLogicalKnobs
;; (: addLogicalKnobs (-> (Tree $a) NodeId Bool (MultiMap ($k $v)) Expression Expression))
(= (addLogicalKnobs $exemplar $nodeId $addIfInExemplar $map $argLabels)
   (let*
     (

      ((mkNodeId $rawPath) $nodeId)
      ((mkTree (mkNode $op) $children) (getNodeById $exemplar $nodeId))
      ;; ($_ (println! (Adding knobs to: (preOrder (mkTree (mkNode $op) $children)))))
      ;; Use complete game moves for strategy operators, argLabels for boolean operators
      ($labels (if (== $op PRIORITIZED-OR) (getAllGameMoves) $argLabels))
      ($lengthOfArgs (length $labels))
      ($perms (if (== $op PRIORITIZED-OR)
                  (sampleStrategyPerms $op $lengthOfArgs $labels $rawPath)
                  (sampleLogicalPerms $op $lengthOfArgs $labels $rawPath)))
      ($treePerms (map-atom $perms $perm (buildTree $perm)))
      (($knobs $updatedTree) (if (== $op PRIORITIZED-OR)
                                 (strategyProbe $exemplar $nodeId $treePerms $addIfInExemplar ())
                                 (logicalProbe $exemplar $nodeId $treePerms $addIfInExemplar ())))

      ;; ($_ (println! (Adding (length $knobs) Knobs)))

      ($pairs (pairKnobWithSpec $knobs))
      ($mmp (expToMMap $pairs $map discSpec<))
      ($temp (cut))
     )
     ($updatedTree $mmp)))
