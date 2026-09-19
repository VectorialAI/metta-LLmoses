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
   (addLogicalKnobs $exemplar $nodeId $addIfInExemplar $map $argLabels True))

(= (addLogicalKnobs $exemplar $nodeId $addIfInExemplar $map $argLabels $disable-discprobe)
   (addLogicalKnobsAt $exemplar $nodeId $nodeId $addIfInExemplar $map $argLabels $disable-discprobe))

;; Keep the upstream logical-probe root/target split while threading the
;; target's raw path into the strategy sampler for contextual utility lookup.
(= (addLogicalKnobsAt $exemplar $probeRootId $nodeId $addIfInExemplar $map $argLabels $disable-discprobe)
   (let*
     (
      ((mkNodeId $rawPath) $nodeId)
      ((mkTree (mkNode $op) $children) (getNodeById $exemplar $nodeId))
      ($labels (if (== $op PRIORITIZED-OR) (getAllGameMoves) $argLabels))
      ($lengthOfArgs (length $labels))
      ($perms (sampleStrategyPerms $op $lengthOfArgs $labels $rawPath))
      ($treePerms (map-atom $perms $perm (buildTree $perm)))
      (($knobs $updatedTree) (strategyProbe $exemplar $nodeId $treePerms $addIfInExemplar ()))
      ($pairs (pairKnobWithSpec $knobs))
      ($mmp (expToMMap $pairs $map discSpec<))
     )
     ($updatedTree $mmp)))

(= (addLogicalKnobs (mkTree (mkNode $op) $children) $addIfInExemplar $map $argLabels)
   (addLogicalKnobsFast (mkTree (mkNode $op) $children) $addIfInExemplar $map $argLabels True (mkTree (mkNode $op) $children) (mkNodeId (0))))

;; Current upstream fast path, with the absolute current-node path passed to
;; the milestone-2 logical permutation sampler.
(= (addLogicalKnobsFast (mkTree (mkNode $op) $children) $addIfInExemplar $map $argLabels $disable-discprobe $globalTree $currentNodeId)
   (let*
     (
      ((mkNodeId $rawPath) $currentNodeId)
      ($lengthOfLabels (size-atom $argLabels))
      ($perms (sampleLogicalPerms $op $lengthOfLabels $argLabels $rawPath))
      ($treePerms (map-atom $perms $perm (buildTree $perm)))
      (($knobs $updatedTree)
        (logicalProbe (mkTree (mkNode $op) $children) $globalTree
                      (mkNodeId (0)) $currentNodeId $treePerms
                      $addIfInExemplar $disable-discprobe))
      ($pairs (pairKnobWithSpec $knobs))
      ($mmp (expToMMap $pairs $map discSpec<))
     )
     ($updatedTree $mmp)))
