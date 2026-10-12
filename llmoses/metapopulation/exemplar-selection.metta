;; LLMOSES overlay of metapopulation/exemplar-selection.metta.
;; The selection temperature comes from the run config, and the roulette draw
;; is made by state_builder.select_index so the responder can weight it.

;; bind is not supported for constants (as of 13 NOV) in PeTTa -- thus using function style notation
(= (NO_EXEMPLAR) "empty metapopulation")
(= (COMPXY_TEMP) (py-call (state_builder.selection_temperature)))
(= (INV_TEMP) (/ 100.0 (COMPXY_TEMP)))

;; exemplar selection
;; if the metapopulation is empty - throw error and quit
;; if only one exemplar in the metapopulation select that
;; if more than one exemplar in mp - convert penalized scores into Boltzmann
;; probability values and draw an index with state_builder.select_index
; (: selectExemplar (-> (OS (Exemplar $a)) (Exemplar $a)))
(= (selectExemplar $metaPop)
    (case $metaPop
        ((() (Error $metaPop (NO_EXEMPLAR)))
        ((cons $x ()) (let* (((mkExemplar $tree $id $cs $bs) $x)
                              ($_one (py-call (state_builder.selection_single $tree)))) $x))
        ($_ (let* (
                    ($probs (getPnScore $metaPop))
                    ($hstScr (List.max $probs))
                    ;; get list of normalized ScoreT values
                    ($normalizedProbs (normalizeProbs (INV_TEMP) $hstScr $probs))
                    ($n (eval (OS.length $metaPop)))
                    ($_b (py-call (state_builder.begin_selection $n)))
                    ($_s (sbStreamSelCands $metaPop $normalizedProbs 0))
                    ($idx (py-call (state_builder.select_index)))
                  )
                  (OS.getByIdx $idx $metaPop) )))))

;; sbStreamSelCands -- sends (index, probability, tree, penalized score) for each
;; member to state_builder ahead of select_index
(= (sbStreamSelCands () () $i) 0)
(= (sbStreamSelCands (cons $x $rest) (cons $p $ps) $i)
   (let* (
     ((mkExemplar $tree $demeId $cscore $bscore) $x)
     ($score (eval (getPenScore $cscore)))
     ($_c (py-call (state_builder.add_selection_candidate $i $p $tree $score)))
   ) (sbStreamSelCands $rest $ps (+ $i 1))))

;; get penalized scores of all the exemplars as a list of Numbers
;;      (cons $x $xs) -- pattern for the list of exemplars constructed by cons
;;      made use of deconstruction by pattern matching

; (: getPnScore (-> (OS (Exemplar $a)) (List Number)))
(= (getPnScore ()) ())
(= (getPnScore (cons $x $xs))
   (let (mkExemplar $tree1 $demeId1 (mkCscore $scrr $cpxy $cpxyPen $uniPen $penScr) $bscr1) $x
        (cons $penScr (getPnScore $xs))))

;;  a function to normalize the score values into normalized scores of Boltzman distribution
;; the function is specific to this distribution type
; (: normalizeProbs (-> Number Number (List Number) (List Number)))
(= (normalizeProbs $invTemp $best ()) ())
(= (normalizeProbs $invTemp $best (cons $x $xs))
    (let*
        (($new (if (isinf-math $x) 0 (exp (* (- $x $best) $invTemp))))
        ($c (normalizeProbs $invTemp $best $xs)))

        (cons $new $c)))

;; the main roulette select function
;;      $metaPop -- (OS (Exemplar $a)) -- list of exemplars
;;      $probs -- (List Number) -- list of prob values as ScoreT types
;;      $sum -- sum of penalized score values after normalization using the (pow-math EXP (* (- $val $higestScr) INV_TEMP))
;;      to favour the selection of high scoring exemplars -- Boltzman distribution
;; LLMOSES: rouletteSelect and roulette are no longer called by selectExemplar
;; (the draw is in state_builder.select_index); kept for reference.
; (: rouletteSelect (-> (OS (Exemplar $a)) (List Number) Number (Exemplar $a)))
(= (rouletteSelect $metaPop $probs $sum)
    (let* (
           ($rndfloat (py-call (random.random))) ;;This was (random-float 0 1)
           ($ajstdSum (* $sum $rndfloat))
           ($index (roulette $probs 0 $ajstdSum))
          )
        (OS.getByIdx $index $metaPop)))

;; roulette function to do the roulette selection and return an index -- spin the wheel
;;      $probs -- (List Number) -- list of prob values
;;      $sIdx -- start index -- 0
;;      $ajstdsum -- sum of probabilities which has been multiplied with a random with random value in (0 .. 1) range
; (: roulette (-> (List Number) Number Number Number))
(= (roulette () $sIdx $ajstdsum) (- $sIdx 1))
(= (roulette (cons $p $xs) $sIdx $ajstdsum)
            (if (<= (- $ajstdsum $p) 0)
            $sIdx
            (roulette $xs (+ 1 $sIdx) (- $ajstdsum $p)))
    )
