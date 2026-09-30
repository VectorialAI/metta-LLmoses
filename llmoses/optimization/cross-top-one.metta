;; Compatibility extension for upstream hill-climbing crossover.
;; Preserve the strategy representation's legacy index map while applying the
;; upstream crossover algorithm to its scored instances.

!(import! &self optimization/hillclimbing/cross-top-one)

(= (llCrossTopOne
      (mkDeme
        (mkRep (mkKbMap (mkDscMp $dscMp)) $tree)
        (mkSInstSet $instSet) $demeId)
      $nToMake $sampleStart $sampleSize $baseInstance)
   (crossTopOne
     (mkDeme
       (mkRep (mkKbMap (mkDscMp $dscMp)) $tree)
       (mkSInstSet $instSet) $demeId)
     $nToMake $sampleStart $sampleSize $baseInstance))

(= (llCrossTopOne
      (mkDeme
        (mkRep (mkKbMap $dscKbMp (mkDscMp $dscMp)) $tree)
        (mkSInstSet $instSet) $demeId)
      $nToMake $sampleStart $sampleSize $baseInstance)
   (let* (
     ($nToMakeNew
       (if (< (- $sampleSize 1) $nToMake) (- $sampleSize 1) $nToMake))
     (($prevInst $newInst) (List.splitAt $sampleStart $instSet))
     ($list (List.partialSort instance> $newInst $nToMakeNew ()))
   )
   (if (== $list ())
       (mkDeme
         (mkRep (mkKbMap $dscKbMp (mkDscMp $dscMp)) $tree)
         (mkSInstSet $instSet) $demeId)
       (let* (
         ((cons $reference $rest) $list)
         ($targetExpr (List.takeN (- $nToMake 1) $rest))
         ((mkSInst (mkPair $referenceInst $referenceScore)) $reference)
         ($newInstances (merger $targetExpr $baseInstance $referenceInst))
       )
       (mkDeme
         (mkRep (mkKbMap $dscKbMp (mkDscMp $dscMp)) $tree)
         (mkSInstSet (List.appendList (exprToList $newInstances) $instSet))
         $demeId)))))
