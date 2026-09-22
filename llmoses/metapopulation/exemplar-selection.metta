;; LLMOSES exemplar overlay: a separately configured native temperature,
;; bounded score offsets, mix then sharpen, one native RNG draw at b=0.
(= (NO_EXEMPLAR) "empty metapopulation")
(= (COMPXY_TEMP) (py-call (state_builder.selection_temperature)))
(= (INV_TEMP) (/ 100.0 (COMPXY_TEMP)))

;; exemplar selection
;; if the metapopulation is empty - throw error and quit
;; if only one exemplar in the metapopulation select that
;; if more than one: normalize penalized scores (Boltzmann), then draw the
;; index through the (possibly utility-biased) Python roulette.
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

;; Stream one (index, native prob, tree) triple per member into the Python
;; selection buffer. Walks the OS and the normalized-prob List in lockstep;
;; the exemplar is destructured directly (this file loads before the
;; metapopulation accessors, mirroring getPnScore below).
(= (sbStreamSelCands () () $i) 0)
(= (sbStreamSelCands (cons $x $rest) (cons $p $ps) $i)
   (let* (
     ((mkExemplar $tree $demeId $cscore $bscore) $x)
     ($score (eval (getPenScore $cscore)))
     ($_c (py-call (state_builder.add_selection_candidate $i $p $tree $score)))
   ) (sbStreamSelCands $rest $ps (+ $i 1))))

;; get penalized scores of all the exemplars as a list of Numbers
;;      (cons $x $xs) -- pattern for the current list/ordered-set representation
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

;; Native rouletteSelect/roulette retained for reference and any external
;; callers; the fork's selectExemplar no longer calls them (the draw happens
;; in state_builder.select_index with identical semantics).
; (: rouletteSelect (-> (OS (Exemplar $a)) (List Number) Number (Exemplar $a)))
(= (rouletteSelect $metaPop $probs $sum)
    (let* (
           ($rndfloat (py-call (random.random)))
           ($ajstdSum (* $sum $rndfloat))
           ($index (roulette $probs 0 $ajstdSum))
          )
        (OS.getByIdx $index $metaPop)))

;; roulette function to do the roulette selection and return an index -- spin the wheel
; (: roulette (-> (List Number) Number Number Number))
(= (roulette () $sIdx $ajstdsum) (- $sIdx 1))
(= (roulette (cons $p $xs) $sIdx $ajstdsum)
            (if (<= (- $ajstdsum $p) 0)
            $sIdx
            (roulette $xs (+ 1 $sIdx) (- $ajstdsum $p)))
    )
