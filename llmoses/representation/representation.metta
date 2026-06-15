;; ============================================================================
;; llmoses/representation/representation.metta
;;
;; Drop-in replacement for representation/representation.metta — do NOT import
;; the upstream file. Tags rep-index during representation build so pair-sampling
;; events align with deme order.
;; buildKnobs / featureSelector / sampleEnforcedFts etc. come from earlier
;; imports in the load order; only the five non-overridden helpers from the
;; upstream surface are copied here.
;; ============================================================================

;; --- inlined helpers from representation/representation ---

(= (crtDiscKnobMap (mkDscMp NilMMap) (mkDscKbMp $dkm) $index) (mkDscKbMp $dkm))
(= (crtDiscKnobMap (mkDscMp (ConsMMap ($kbSpec $kb) $tail)) (mkDscKbMp $dkm) $index)
   (let*
   (
    ($loc (getKnobLoc $kb))
    ($updatedDkm (Map.insert ($loc $index) $dkm == nodeId<))
   )
   (crtDiscKnobMap (mkDscMp $tail) (mkDscKbMp $updatedDkm) (+ $index 1))
  ))

(= (getRepTree (mkRep $knobMapObj $tree)) $tree)

(= (getCandidate $repObj $inst)
   (let*
      (
         ($parentid (mkNodeId (0)))
         ($srcid (mkNodeId (0)))
         ((mkRep $kmo $tr) $repObj)
         ($candidate (getCandidateRec $repObj $inst $parentid $srcid $parentid (mkNullVex Nil)))
         ($rootNode (getNodeById (getRepTree $repObj) $srcid))
         ($rootValue (getNodeValue $rootNode))
         ($rootSymbol (if (== (get-metatype $rootValue) Expression)
                 (car-atom (cdr-atom $rootValue))
                 $rootValue))
         ($isGameStrategy (== $rootSymbol PRIORITIZED-OR))
      )
      (if $isGameStrategy
          (let* (
                  ($expr (preOrder $candidate))
                  ($cleanTree (buildTree $expr)))
                $cleanTree)
          (cleanTree $candidate))))

(= (getCandidateRec (mkRep $knobMapObj $tree) (mkInst $inst) $parentId $srcId $dstId $candidate)
   (let $knobIdxPair (findDiscKnob $knobMapObj $srcId)
      (if (not (== (second $knobIdxPair) -1))
         (let*
            (
               ($d (List.getByIdx $inst (second $knobIdxPair)))
               ($result  (appendTo $tree (first $knobIdxPair) $candidate $dstId $d))
               (($updatedCnd $newSrcId $newDstId) $result)
            )
            (if (== $updatedCnd $candidate)
                $updatedCnd
                (let*
                   (
                      ($src1 (getNodeById $tree $newSrcId))
                      ($srcchildren1 (getChildren $src1))
                      ($state1 (List.foldl applyGetCandidateRec ((mkRep $knobMapObj $tree) (mkInst $inst) $newSrcId $newDstId $updatedCnd 1) $srcchildren1))
                      (((mkRep $knobmapobj1 $tree1) (mkInst $inst1) $newparentid1 $newdstId1 $finalcnd1 $d1) $state1)
                   )
                   $finalcnd1
                )
            )
         )
         (let*
            (
               ($src (getNodeById $tree $srcId))
               ($dstValue (getNodeById $candidate $dstId))
               ($cndchidpair (appendChild $candidate $dstId (mkTree (getNodeValue $src) Nil)))
               ($srcchildren (getChildren $src))
               ($state (List.foldl applyGetCandidateRec ((mkRep $knobMapObj $tree) (mkInst $inst) $srcId (second $cndchidpair) (first $cndchidpair) 1) $srcchildren))
               (((mkRep $knobmapobj $tree) (mkInst $inst) $newparentid $newdstId $finalcnd $d) $state)
            )
              $finalcnd
          )
      )
   )
)

(= (applyGetCandidateRec $tr ($repObj $inst (mkNodeId $parentId) (mkNodeId $dstId) $candidate $chIdx))
   (let*
      (
         ($srcId (if (== $parentId (0)) (mkNodeId ($chIdx)) (mkNodeId (concatT $parentId ($chIdx)))))
         ($updatedCnd1 (getCandidateRec $repObj $inst (mkNodeId $parentId) $srcId (mkNodeId $dstId) $candidate))
         ($finalResult ($repObj $inst (mkNodeId $parentId) (mkNodeId $dstId) $updatedCnd1 (+ 1 $chIdx)))
      )
      $finalResult
   )
)

;; --- overlay definitions (add sbSetPairSamplingRepIndex / sbIncPairSamplingRepIndex hooks) ---

;; Game strategy path: one rep per deme index from collapse superpose.
(= (representation $exemplar $nDeme)
   (let* (
      ($demeCount (range 0 1 $nDeme))
      ($result (collapse (let $x (superpose $demeCount)
         (let*
            (
               ($_ (eval (sbSetPairSamplingRepIndex $x)))
               (($updatedTree $dscMp) (buildKnobs $exemplar NilMMap ()))
               ($dscKbMp (crtDiscKnobMap (mkDscMp $dscMp) (mkDscKbMp NilMap) 0))
               ($rep (mkRep (mkKbMap $dscKbMp (mkDscMp $dscMp)) $updatedTree))
            )
               $rep))))
   )
   $result))

;; Boolean path: advance rep index after each feature-set rep build.
(= (representation
            $nDeme
            $exemplar
            (mkITable $table $labels)
            $ft-selection-algo
            $prune-exemplar
            $enforced-fts
            $scorerType
        )
        (let* (
                  ($exemplar-fts  (filter-atom (treeFtsIndices $exemplar $labels) $x (not (== $x -1))))
                 ($all-labels (getInputLabels $labels))
                 ($ft-set-pop (if (== $ft-selection-algo None)
                                  ((genList 0 (- (List.length $labels) 2)))
                                  (featureSelector $ft-selection-algo (mkITable $table $labels) 0.0 $exemplar 2 2 False () False 2 False ja $nDeme 50.0 1.0 0.5 1.0 True $scorerType))
                 )
                 ($exemplar-arg-seq
                     (if $prune-exemplar
                           (map-atom $ft-set-pop $ft-set 
                              (let* (($diff-ft (subtraction-atom $exemplar-fts $ft-set))
                                     ($ft-names (fsToNames $labels $diff-ft))
                                     ($pruned-xmplr (pruneExemplar $exemplar $ft-names))
                                     ($final-args (subtraction-atom $ft-set $exemplar-fts)))
                                 ($pruned-xmplr (fsToNames $labels $final-args))))
                           (map-atom $ft-set-pop $ft-set 
                                 (let* (($agg (union-atom-set $ft-set $exemplar-fts))
                                        ($final-args (fsToNames $labels $agg)))
                                    ($exemplar $final-args)))))
                  ($with-enforced-fts
                     (if (== $enforced-fts ())
                           $exemplar-arg-seq
                           (let $sampled-enforced-fts (sampleEnforcedFts $enforced-fts)
                                    (map-atom $exemplar-arg-seq ($xmplr $args)
                                             (let $acc (concatT $args $sampled-enforced-fts) ($xmplr $acc))))))
                  ($filter-empty-args (filter-atom $with-enforced-fts ($xmplr $args) (not (== $args ()))))
              )
                     (map-atom $filter-empty-args ($xmplr $argLabels) 
                           (let* (
                                    (($updatedTree $dscMp) (buildKnobs $xmplr NilMMap $argLabels))
                                    ($dscKbMp (crtDiscKnobMap (mkDscMp $dscMp) (mkDscKbMp NilMap) 0))
                                    ($rep (mkRep (mkKbMap $dscKbMp (mkDscMp $dscMp)) $updatedTree))
                                    ($_ (eval (sbIncPairSamplingRepIndex))))
                                 $rep)))))
