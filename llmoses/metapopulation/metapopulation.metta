;; llmoses/metapopulation/metapopulation.metta
;;
;; LLMOSES fork of metapopulation/metapopulation.metta (import INSTEAD of the
;; base file — never both, D-FSFORK). Two Phase II levers live here:
;;
;;   Lever 2a — directed culling: cullAtRandom streams the removable tail
;;   [offset-1, popSize-1] (exactly the native randint(offset, popSize)-1
;;   range) to Python; state_builder.cull_index() picks the member to remove,
;;   weighted by (1 - retention_utility) when the culling lever is on, uniform
;;   (native-identical) otherwise.
;;
;;   Lever 3 — comparator ordering: compareExemplar consults Python first;
;;   -1/0/1 apply the response's program_id_ordering (only when it covers BOTH
;;   exemplars), 2 falls through to the verbatim native comparison MeTTa-side,
;;   so the off path is exactly native.

;; Exemplar type
(: Exemplar (-> $a Type))
(: mkExemplar (-> (Tree $a) DemeId Cscore BehavioralScore (Exemplar $a)))

;; resizeMetapop -- resizes the metapopulation based on
;;      $nToKeep     -- the number of the top most exemplars which are exempt from removal
;;      $minPoolSize -- protects the metapopulation against excessive trimming
;;      $compTemp    -- used to calculate the range of scores that are likely to be preserved by the selection process
;;      $capCoef     -- use to balance the number of individuals in the metapopulation
;;      $genCount    -- used with $capCoef in the determination of max pop allowed

;; compute useful range
; (: usefulScoreRange (-> Number Number))
(= (usefulScoreRange $compTemp) (/ (* $compTemp 30.0) 100.0))

; (: resizeMetapop (-> (OS (Exemplar $a)) Number Number Number Number Number (OS (Exemplar $a))))
(= (resizeMetapop (ConsOS $exemplar $rest) $nToKeep $minPoolSize $compTemp $capCoef $genCount)
    (let ($size $capSize) ((OS.length (ConsOS $exmplar $rest)) (int (capSize $capCoef $genCount))) ;; bind two variables with two function calls
        (if (<= $size $minPoolSize)
            (ConsOS $exemplar $rest)
            (let*
              (
               ((mkExemplar $tree $demeId $cScore $bScore) $exemplar) ;; exemplar with the best score

               ($topScore (getPenScore $cScore))
               ($worstScore (- $topScore (usefulScoreRange $compTemp)))

               ($reducedMetapop (getBetterCandidates (ConsOS $exemplar $rest) $worstScore))
               ($popSize (OS.length $reducedMetapop))
              )
              (if (<= $popSize $capSize)
                  $reducedMetapop
                  (cullAtRandom $reducedMetapop $nToKeep (- $popSize $capSize)))
           ))))
;;TODO: for large minPoolSize if the returned resizedMetapop size is less than minPoolSize we may still need to add random candidates to reach minPoolSize

;; calculates cap size based on number of generations
; (: capSize (-> Number Number Number))
(= (capSize $capCoef $genCount)
    (* (* $capCoef (+ $genCount 250)) (+ 1 (* 2 (exp (/ (* -1 $genCount) 500))))))

;; getBetterCandidates -- returns all the members whose score are greater than or equal to a predetermined worst score
; (: getBetterCandidates (-> (OS (Exemplar $a)) Number (OS (Exemplar $a))))
(= (getBetterCandidates NilOS $score) NilOS)
(= (getBetterCandidates (ConsOS $exemplar $rest) $worstScore)
    (let (mkExemplar $tree $demeId $cScore $bScore) $exemplar
            (chain (getPenScore $cScore) $penScore

                (if (>= $penScore $worstScore)
                    (ConsOS $exemplar (getBetterCandidates $rest $worstScore))
                    NilOS))))

;; cullAtRandom -- maintains the top exemplars and removes lower-ranked members.
;; LLMOSES lever 2a: the removable tail is streamed to Python and the index to
;; remove comes from state_builder.cull_index() — uniform over the exact native
;; range when the culling lever is off, retention-weighted when on.
; (: cullAtRandom (-> (OS (Exemplar $a)) Number Number (OS (Exemplar $a))))
(= (cullAtRandom (ConsOS $exemplar $rest) $offset $nToRemove)
   (let $popSize (OS.length (ConsOS $exemplar $rest))
    (if (and (> $popSize $offset) (> $nToRemove 0))
        (let*
          (
           ($_b (py-call (state_builder.begin_cull $offset $popSize)))
           ($_s (sbStreamCullCands (ConsOS $exemplar $rest) 0 (- $offset 1)))
           ($index (py-call (state_builder.cull_index)))
           ($newPop (OS.removeByIdx (ConsOS $exemplar $rest) $index))
          )
          (cullAtRandom $newPop $offset (- $nToRemove 1))
        )
        (ConsOS $exemplar $rest))))

;; Stream one (index, tree) pair per removable member [minIdx, popSize-1] into
;; the Python cull buffer (the proven per-member streaming pattern).
(= (sbStreamCullCands NilOS $i $minIdx) 0)
(= (sbStreamCullCands (ConsOS $x $rest) $i $minIdx)
   (if (< $i $minIdx)
       (sbStreamCullCands $rest (+ $i 1) $minIdx)
       (let* (
         ((mkExemplar $tree $demeId $cscore $bscore) $x)
         ($_c (py-call (state_builder.add_cull_member $i $tree)))
       ) (sbStreamCullCands $rest (+ $i 1) $minIdx))))

;; Compares two exemplars based on their Cscores, returning L if the first is less, E if equal, or G if greater.
;; LLMOSES lever 3: Python returns 2 whenever the comparator lever is not
;; applicable, and the native comparison below runs unchanged.
; (: compareExemplar (-> (Exemplar $a) (Exemplar $a) Atom))
(= (compareExemplar
        (mkExemplar $tree1 $demeId1 $cscore1 $bscr1)
        (mkExemplar $tree2 $demeId2 $cscore2 $bscr2))
   (let* (($c (py-call (state_builder.compare_exemplars $tree1 $tree2))))
     (if (== $c 2)
         (if (apply < $cscore1 $cscore2) L
             (if (== $tree1 $tree2) E G)) ;; If they are the same tree, they will have the same $cscore
         (if (== $c 0) E (if (== $c -1) L G)))))

;; LLMOSES lever 3 application point: re-sort the metapopulation through
;; compareExemplar (which consults the response's program_id_ordering). Called
;; from runMosesLoop at the top of each generation when the comparator lever
;; is on — every member is already known to the response there, unlike merge
;; inserts, whose incoming candidates are born after the response.
(= (llmResortMetapop $os) (llmResortIns $os NilOS))
(= (llmResortIns NilOS $acc) $acc)
(= (llmResortIns (ConsOS $x $rest) $acc)
   (llmResortIns $rest (OS.insert compareExemplar $x $acc)))

;; Extract BScore from Exemplar
; (: getExemplarBScore (-> (Exemplar $a) BehavioralScore))
(= (getExemplarBScore (mkExemplar $tree $demeId $cscore $bscore)) $bscore)

;; Extract PenScore from Exemplar
; (: getExemplarPenScore (-> (Exemplar $a) Number))
(= (getExemplarPenScore (mkExemplar $tree $demeId $cscore $bscore)) (getPenScore $cscore))

;; Extract Cscore from Exemplar
; (: getExemplarCscore (-> (Exemplar $a) Cscore))
(= (getExemplarCscore (mkExemplar $tree $demeId $cscore $bscore)) $cscore)

;; Extract Tree from Exemplar
; (: getExemplarTree (-> (Exemplar $a) (Tree $a)))
(= (getExemplarTree (mkExemplar $tree $demeId $cscore $bscore)) $tree)
