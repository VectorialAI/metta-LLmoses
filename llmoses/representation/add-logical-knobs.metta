;; LLMOSES overlay of representation/add-logical-knobs.metta.
;; The permutation samplers also receive the target node's path, so the
;; atom-pair policy can condition on where in the tree knobs are added.

;;;;;;;; addLogicalKnotree knobs in to a multimap
;; Params:
;;   $exemplar: Reference tree containing the target node.
;;   (mkNodeId $targetId): ID of the target node in the exemplar.
;;   $addIfInExemplar: If true, include knobs even if in exemplar.
;;   $map: a multimap to add the new knobs into
;;   $argLabels: list of argument labels (input variables) from the ITable
;;   $disable-discprobe: (optional, default True) passed through to the probe
;; Return: a multimap of ($knobSpec $knob) and the updated tree

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

;; addLogicalKnobsAt keeps the logical probe root distinct from the target node.
;; Strategy knobs ignore the root and are not disc-probed.
(= (addLogicalKnobsAt $exemplar $probeRootId $nodeId $addIfInExemplar $map $argLabels $disable-discprobe)
   (let*
     (
      ((mkNodeId $rawPath) $nodeId)
      ((mkTree (mkNode $op) $children) (getNodeById $exemplar $nodeId))
      ;; Use complete game moves for strategy operators, argLabels for boolean operators
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

;; addLogicalKnobsFast -- boolean (AND/OR) path used by buildLogical
;;   $globalTree, $currentNodeId: the full exemplar and the absolute path of this node
;;   $causalPath: child positions from the root to this knob site (LLMOSES)
;;   $siteKind: exemplar_node, appended_child, literal_wrap or sampled_subtree (LLMOSES)
;; The 7-argument form starts at the root: empty $causalPath, exemplar_node.
(= (addLogicalKnobsFast (mkTree (mkNode $op) $children) $addIfInExemplar $map $argLabels $disable-discprobe $globalTree $currentNodeId $causalPath $siteKind)
   (let*
     (
      ((mkNodeId $rawPath) $currentNodeId)
      ($lengthOfLabels (size-atom $argLabels))
      ($perms (sampleLogicalPerms $op $lengthOfLabels $argLabels $causalPath $siteKind $children))
      ($treePerms (map-atom $perms $perm (buildTree $perm)))
      ;; logicalProbe now receives: $localTree (current subtree) + $globalTree
      ;; (static exemplar context) + $probeRootId (stays (mkNodeId (0)),
      ;; reserved for future tighter scopes) + $targetId (absolute path to
      ;; current subtree's root in the global tree).
      (($knobs $updatedTree)
        (logicalProbe (mkTree (mkNode $op) $children) $globalTree
                      (mkNodeId (0)) $currentNodeId $treePerms
                      $addIfInExemplar $disable-discprobe))
      ;; links the new knobs to the pairs drawn at this site, for the atom-pair policy
      ($_pairTags (py-call (state_builder.register_pair_knobs $updatedTree $causalPath)))
      ($pairs (pairKnobWithSpec $knobs))
      ($mmp (expToMMap $pairs $map discSpec<))
     )
     ($updatedTree $mmp)))

(= (addLogicalKnobsFast $tree $add $map $labels $disc $global $nodeId)
   (addLogicalKnobsFast $tree $add $map $labels $disc $global $nodeId () exemplar_node))
