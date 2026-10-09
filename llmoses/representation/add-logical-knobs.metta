;; ============================================================================
;; llmoses/representation/add-logical-knobs.metta
;;
;; Drop-in replacement for representation/add-logical-knobs.metta — do NOT
;; import the upstream file (D-FSFORK: one copy per function, ever).
;;
;; Causal policy metadata is threaded explicitly; probe paths stay native.
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
(= (addLogicalKnobsFast (mkTree (mkNode $op) $children) $addIfInExemplar $map $argLabels $disable-discprobe $globalTree $currentNodeId $causalPath $siteKind)
   (let*
     (
      ((mkNodeId $rawPath) $currentNodeId)
      ($lengthOfLabels (size-atom $argLabels))
      ($perms (sampleLogicalPerms $op $lengthOfLabels $argLabels $causalPath $siteKind $children))
      ($treePerms (map-atom $perms $perm (buildTree $perm)))
      (($knobs $updatedTree)
        (logicalProbe (mkTree (mkNode $op) $children) $globalTree
                      (mkNodeId (0)) $currentNodeId $treePerms
                      $addIfInExemplar $disable-discprobe))
      ($_pairTags (py-call (state_builder.register_pair_knobs $updatedTree $causalPath)))
      ($pairs (pairKnobWithSpec $knobs))
      ($mmp (expToMMap $pairs $map discSpec<))
     )
     ($updatedTree $mmp)))

(= (addLogicalKnobsFast $tree $add $map $labels $disc $global $nodeId)
   (addLogicalKnobsFast $tree $add $map $labels $disc $global $nodeId () exemplar_node))
