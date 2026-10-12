;; LLMOSES overlay of moses/neighborhood-sampling.metta. Imports upstream and
;; adds a sampleNewInstances clause for strategy representations, which still
;; use the two-field (mkKbMap $dscKbMp (mkDscMp $disc)); upstream only handles
;; the one-field form used by boolean representations.

!(import! &self moses/neighborhood-sampling)

(= (sampleNewInstances
      $totalNeighbors $numNewInstances $centerInst
      (mkDeme
        (mkRep (mkKbMap $dscKbMp (mkDscMp $disc)) $tree)
        (mkSInstSet $instList) $demeId)
      $dist)
   (let* (
     ($discOnly (mkKbMap (mkDscMp $disc)))
     ($updatedTotalNeighbors
       (if (> (* 2 $numNewInstances) $totalNeighbors)
           (countNeighborhood $discOnly $centerInst $dist $numNewInstances)
           $totalNeighbors))
     ($updatedNumNewInstances
       (if (< $numNewInstances $updatedTotalNeighbors)
           $numNewInstances
           $updatedTotalNeighbors))
     ($newInstances
       (if (< $numNewInstances $updatedTotalNeighbors)
           (sampleFromNeighborhood $numNewInstances $dist $discOnly $centerInst)
           (generateAllInNeighborhoodForDisc (mkDscMp $disc) $centerInst $dist)))
     ($scoredNewInstances (List.map initInstScore $newInstances))
     ($updatedInstList (List.concat $instList $scoredNewInstances))
   )
   ((mkDeme
      (mkRep (mkKbMap $dscKbMp (mkDscMp $disc)) $tree)
      (mkSInstSet $updatedInstList) $demeId)
    $updatedNumNewInstances)))
