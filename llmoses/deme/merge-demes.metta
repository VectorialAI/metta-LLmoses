;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;            LLMOSES – Merge Demes                  ;;
;;                                                   ;;
;; Fork of deme/merge-demes.metta with one change:   ;;
;;   sbEmitCullCands is wrapped in (eval ...) so that ;;
;;   runtime dispatch finds the definition that lives ;;
;;   in llmoses/wrapper/state-builder.metta, which is ;;
;;   loaded AFTER this file and would otherwise be    ;;
;;   compiled to a no-op (true) by MeTTaLog.          ;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;; Removes adjacent duplicate ScoredInstances from a sorted list, keeping up to $topCnd unique instances.
;; Params:
;;    (List (ScoredInstance Cscore)): Sorted list of scored instances.
;;    $topCnd: Maximum number of instances to keep.
;; Return: (List (ScoredInstance Cscore)): List with adjacent duplicates removed, limited by $topCnd.
; (: removeDupInsts (-> (List (ScoredInstance Cscore)) Number (List (ScoredInstance Cscore))))
(= (removeDupInsts $rep Nil $topCnd) Nil)
(= (removeDupInsts $rep (Cons $x Nil) $topCnd)
   (if (> $topCnd 0) (Cons $x Nil) Nil))
(= (removeDupInsts $rep (Cons (mkSInst $x) (Cons (mkSInst $y) $rest)) $topCnd)
   (let $lengthOfTail (List.length (Cons (mkSInst $y) $rest))
   (if (> $topCnd 0)
       (if (isApproxEq (getPenScore (Pair.second $x)) (getPenScore (Pair.second $y))) ;; They maybe identical
           (let*
              (
                ($tr1 (getCandidate $rep (Pair.first $x)))
                ($tr2 (getCandidate $rep (Pair.first $y)))
                ;; ($_ (println! (Tree1: (preOrder $tr1) Tree2: (preOrder $tr2))))
              )
              (if (== $tr1 $tr2)
                  (removeDupInsts $rep (Cons (mkSInst $x) $rest) (min-atom ($topCnd $lengthOfTail)))
                  (Cons (mkSInst $x) (removeDupInsts $rep (Cons (mkSInst $y) $rest) (- $topCnd 1))) ;; Keep $x, reduce topCnd
              )
           )
           (Cons (mkSInst $x) (removeDupInsts $rep (Cons (mkSInst $y) $rest) (- $topCnd 1))))  ;; Keep $x, reduce topCnd
       Nil)))

;; Extracts up to $maxCandsPerDeme unique ScoredInstances from a sorted InstanceSet, limited by $nEval.
;; Params:
;;   (InstanceSet Cscore): Sorted set of scored instances.
;;   $nEval: Maximum evaluations.
;;   $maxCandsPerDeme: Maximum candidates per deme.
;; Return: (List (ScoredInstance Cscore)): List of unique top-scoring instances.
; (: keepTopUniqueCandidates (-> (InstanceSet Cscore) Number Number (List (ScoredInstance Cscore))))
(= (keepTopUniqueCandidates $rep (mkSInstSet $sortedSInstList) $nEval $maxCandsPerDeme)
 (let*
 (
    ($lenSInstList (List.length $sortedSInstList))
    ($_ (println! (nEval: $nEval LenSInstList: $lenSInstList)))
    ($topCnd (min-atom ($nEval $lenSInstList)))
    ($_ (println! (TopCnd: $topCnd)))
    ($uTopCnd (if (>= $maxCandsPerDeme 0) (min-atom ($topCnd $maxCandsPerDeme)) $topCnd))
    ($_ (println! (Keep $uTopCnd Unique instances from (List.length $sortedSInstList))))
    ($uniqueTopCandidates (removeDupInsts $rep $sortedSInstList $uTopCnd))
 )
 $uniqueTopCandidates
 ))

;; Filters a sorted list of ScoredInstances, removing instances with penalized scores below $botSc, starting from $lastIndex.
;; Params:
;;   (List (ScoredInstance Cscore)): Sorted list of scored instances.
;;   $lastIndex: Index to start checking from (end of list).
;;   $botSc: Minimum penalized score threshold.
;; Return: (List (ScoredInstance Cscore)): Filtered list with low-scoring instances removed.
; (: filterDemeByScore (-> (List (ScoredInstance Cscore)) Number Number (List (ScoredInstance Cscore))))
(= (filterDemeByScore Nil $lastIndex $botSc) Nil)
(= (filterDemeByScore (Cons $x $xs) $lastIndex $botSc)
(if (== $lastIndex 0) (Cons $x $xs) (let*
(
   ($listOfScoredInsts (Cons $x $xs))
   ($lastSInst (List.getByIdx $listOfScoredInsts $lastIndex))
   ($lastSInstScore (getSInstScore $lastSInst))
   ($lastSInstPenScore (getPenScore $lastSInstScore))
)
(if (< $lastSInstPenScore $botSc) 
    (let $lastRemovedList (List.removeAtIdx $listOfScoredInsts $lastIndex) (filterDemeByScore $lastRemovedList (- $lastIndex 1) $botSc))
    (filterDemeByScore $listOfScoredInsts (- $lastIndex 1) $botSc)
    )
)))

;; Trims a sorted list of ScoredInstances to remove low-scoring instances based on a score range derived from $complexityTemperature, unless size ≤ $minPoolSize or 1.
;; Params:
;;   (List (ScoredInstance Cscore)): Sorted list of scored instances.
;;   $minPoolSize: Minimum number of instances to retain.
;;   $complexityTemperature: Parameter for computing score range.
;;Return: (List (ScoredInstance Cscore)): Trimmed list of instances.
; (: trimDownDeme (-> (List (ScoredInstance Cscore)) Number Number (List (ScoredInstance Cscore))))
(= (trimDownDeme $sInstList $minPoolSize $complexityTemperature)
(let $demeSize (List.length $sInstList)
(if (or (>= $minPoolSize $demeSize) (<= $demeSize 1)) 
    $sInstList
    (let*
      (
       ($topInst (List.head $sInstList))
       ($topScore (getSInstScore $topInst))
       ($topPenScore (getPenScore $topScore))
       ($botSc (- $topPenScore (usefulScoreRange $complexityTemperature)))
       ($filteredSInstList (filterDemeByScore $sInstList (- $demeSize 1) $botSc)))     
       $filteredSInstList))))

;; Converts a Deme into a list of Exemplars by transforming each ScoredInstance into a scored tree.
;; Params:
;;   $deme: A deme containing a representation, scored instance set, and demeId.
;;   $itable: The input table.
;; Return: (List (Exemplar $a)) - List of exemplars with scored trees.
; (: demeToTrees (-> Deme (ITable $a) (List (Exemplar $a))))
(= (demeToTrees (mkDeme $rep (mkSInstSet Nil) $demeId) $scoringContext) Nil)
(= (demeToTrees (mkDeme $rep (mkSInstSet (Cons $si $sil)) $demeId) $scoringContext)
(let*
    (
        ($cscore (getSInstScore $si))
        ($inst (getInst $si))
        ($tree (getCandidate $rep $inst))
        ($_ (println! (ScoringContext: $scoringContext)))
        ($bscore (case $scoringContext
                    (((mkITable $rows $labels) (scoreTree $scoringContext $tree &bscoreCache))
                     (($nGames $opponentPolicy) (scoreStrategyTree $tree $nGames $opponentPolicy &strategyScoreCache)))))
        ($scoredTree (mkExemplar $tree $demeId $cscore $bscore))
    )
    (Cons $scoredTree (demeToTrees (mkDeme $rep (mkSInstSet $sil) $demeId) $scoringContext))
    )
)

;; ── LLMOSES dedup guard ─────────────────────────────────────────────────────
;; getNewCandidates' stock test is OS.isMember = full structural == INCLUDING
;; demeId, so the same program arriving from two feature-set demes (identical
;; tree, different demeId) reads as "new" and gets inserted twice.
;; This can't be fixed with an ordering comparator: compareExemplar is
;; non-antisymmetric on cscore ties (returns G both directions for distinct trees
;; at equal score), and genericCompare is non-antisymmetric on symbols (distinct
;; node symbols also compare G both ways) — neither yields a safe total order on
;; trees, so OS.insert's E-dedup can be skipped past a non-adjacent twin. Exact
;; tree equality is the only trustworthy primitive, so we dedup on that.
(= (osHasTree $tree NilOS) False)
(= (osHasTree $tree (ConsOS $x $rest))
   (if (== $tree (getExemplarTree $x)) True (osHasTree $tree $rest)))
;; Filters a sorted list of Exemplars, keeping only those not already in the metaPop (ordered set).
;; Params:
;;   (List (Exemplar $a)): List of exemplars to filter.
;;   $metaPop: Ordered set of existing exemplars.
;; Return: (List (Exemplar $a)): List of new exemplars not in metaPop.
; (: getNewCandidates (-> (List (Exemplar $a)) (OS (Exemplar $a)) (List (Exemplar $a))))
(= (getNewCandidates Nil $metaPop) Nil)
(= (getNewCandidates (Cons $xmp $xmpl) $metaPop)
   (if (osHasTree (getExemplarTree $xmp) $metaPop)
       (getNewCandidates $xmpl $metaPop)
       (let $updatedMetaPop (OS.insert compareExemplar $xmp $metaPop)
            (Cons $xmp (getNewCandidates $xmpl $updatedMetaPop)))))

;; Determines if one BehavioralScore dominates another by comparing their score lists.
; (: dominates (-> BehavioralScore BehavioralScore Atom))
(= (dominates (mkBScore Nil) (mkBScore Nil)) Indeterminate)
(= (dominates (mkBScore Nil) (mkBScore (Cons $by $bys))) False)
(= (dominates (mkBScore (Cons $bx $bxs)) (mkBScore Nil)) True)
(= (dominates (mkBScore (Cons $bx $bxs)) (mkBScore (Cons $by $bys)))
   (dominatesRec (mkBScore (Cons $bx $bxs)) (mkBScore (Cons $by $bys)) Indeterminate))

;; helper function for dominates
; (: dominatesRec (-> BehavioralScore BehavioralScore Atom Atom))
(= (dominatesRec (mkBScore Nil) (mkBScore Nil) $res) $res)
(= (dominatesRec (mkBScore (Cons $bx $bxs)) (mkBScore (Cons $by $bys)) $res)
   (if (> $bx $by)
       (if (== $res False) 
           Indeterminate
           (dominatesRec (mkBScore $bxs) (mkBScore $bys) True))
       (if (> $by $bx)
           (if (== $res True)
               Indeterminate
               (dominatesRec (mkBScore $bxs) (mkBScore $bys) False))
           (dominatesRec (mkBScore $bxs) (mkBScore $bys) $res))))

;; Removes dominated exemplars from a list based on their BehavioralScores.
; (: removeDominated (-> (List (Exemplar $a)) (List (Exemplar $a))))
(= (removeDominated Nil) Nil)
(= (removeDominated (Cons $exemplar Nil)) (Cons $exemplar Nil))
(= (removeDominated (Cons $exemplar (Cons $next $rest)))
   (removeDominatedRec $exemplar (Cons $next $rest) Nil))

;; Helper: Compares an exemplar with others, accumulating non-dominated exemplars.
; (: removeDominatedRec (-> (Exemplar $a) (List (Exemplar $a)) (List (Exemplar $a)) (List (Exemplar $a))))
(= (removeDominatedRec $exemplar Nil $acc)
   (Cons $exemplar $acc))
(= (removeDominatedRec $exemplar (Cons $other $rest) $acc)
   (let $domResult (dominates (getExemplarBScore $exemplar) (getExemplarBScore $other))
      (if (== $domResult True)
          (removeDominatedRec $exemplar $rest $acc)
          (if (== $domResult False)
              (removeDominated (Cons $other $rest))
              (removeDominatedRec $exemplar $rest (Cons $other $acc))))
      ))

;; Merges a list of exemplars into the metapopulation.
; (: mergeCandidates (-> (List (Exemplar $a)) (OS (Exemplar $a)) (OS (Exemplar $a))))
(= (mergeCandidates Nil $metapop) $metapop)
(= (mergeCandidates (Cons $x $xs) $metapop)
   (let $updatedMetaPop (OS.insert compareExemplar $x $metapop)
      (mergeCandidates $xs $updatedMetaPop)))

;; Merges a deme's candidates into a metapopulation.
;; LLMOSES change: (eval (sbEmitCullCands ...)) forces runtime dispatch so that
;; the definition in state-builder.metta (loaded after this file) is found.
; (: mergeDemes (-> Expression Number Number Number Number (ITable $a) (OS (Exemplar $a)) Number Number Number (OS (Exemplar $a))))
(= (mergeDemes $demes $nEval $maxCandsPerDeme $minPoolSize $complexityTemperature $scoringContext $metapop $nToKeep $capCoef $genCount)
    (if (== $demes ()) $metapop
        (let*
        (
            (($headDeme $tailDeme) (decons-atom $demes))
            ((mkDeme $rep $sInstList $demeId) $headDeme)
            ($sortedSInstList (sortDeme $sInstList))
            ($_ (println! (Demesize: (List.length (second $sortedSInstList)))))
            ($unqCandidates (keepTopUniqueCandidates $rep $sortedSInstList $nEval $maxCandsPerDeme))
            ($_ (println! (KeptUniqueTopCandidates NewSize: (List.length $unqCandidates))))
            ($trimmedDeme (trimDownDeme $unqCandidates $minPoolSize $complexityTemperature))
            ($_ (println! (TrimmedDownDeme: (List.length $trimmedDeme))))
            ($potCandidates (demeToTrees (mkDeme $rep (mkSInstSet $trimmedDeme) $demeId) $scoringContext))
            ($_ (println! (Before getNewCandidates: (List.length $potCandidates))))
            ($_ (py-call (state_builder.set_merge_count "candidates_produced" (List.length $potCandidates))))
            ($candidates (getNewCandidates $potCandidates $metapop))
            ($_ (py-call (state_builder.set_merge_count "duplicates_dropped" (- (List.length $potCandidates) (List.length $candidates)))))
            ($removedDominated (removeDominated $candidates))
            ($_ (py-call (state_builder.set_merge_count "dominated_removed" (- (List.length $candidates) (List.length $removedDominated)))))
            ($_ (eval (sbEmitCullCands $removedDominated)))    ;; <-- LLMOSES: eval forces runtime dispatch
            ($_ (println! (Going to merge (List.length $removedDominated) Instances)))
            ($updatedMetaPop (mergeCandidates $removedDominated $metapop))
            ($_ (println! (Metapop size before resize: (OS.length $updatedMetaPop))))
            ($resizedMetapop (resizeMetapop $updatedMetaPop $nToKeep $minPoolSize $complexityTemperature $capCoef $genCount))
            ($_ (println! (Metapop size after resize: (OS.length $resizedMetapop))))
        )
            (if (== $tailDeme ()) $resizedMetapop
                (mergeDemes $tailDeme $nEval $maxCandsPerDeme $minPoolSize $complexityTemperature $scoringContext $resizedMetapop $nToKeep $capCoef $genCount)
            )
        )
    )
)
