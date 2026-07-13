;; llmoses/metapopulation/exemplar-selection.metta
;;
;; LLMOSES fork of metapopulation/exemplar-selection.metta (import INSTEAD of
;; the base file — never both, D-FSFORK). Phase II lever 1: exemplar selection.
;;
;; The native Boltzmann machinery is kept intact: getPnScore -> normalizeProbs
;; produce the same native probability numerators. The only change is the draw
;; site — instead of the MeTTa rouletteSelect, the fork streams
;; (index, native-prob, tree) per member to Python (the proven sbEmitMembers
;; pattern) and state_builder.select_index() performs the roulette there,
;; applying the utility bias w' = w_native * (lam*u^(1/T) + (1-lam)) when the
;; exemplar_selection lever is on. Lever off: same roulette over the same
;; native numerators with the same process-wide RNG (random.random), so the
;; off path is distribution-identical to native. Returns a scalar index; the
;; exemplar is fetched MeTTa-side via OS.getByIdx.

(= (NO_EXEMPLAR) "empty metapopulation")
(= (COMPXY_TEMP) 6)
(= (INV_TEMP) (/ 100.0 (COMPXY_TEMP)))

;; exemplar selection
;; if the metapopulation is empty - throw error and quit
;; if only one exemplar in the metapopulation select that
;; if more than one: normalize penalized scores (Boltzmann), then draw the
;; index through the (possibly utility-biased) Python roulette.
; (: selectExemplar (-> (OS (Exemplar $a)) (Exemplar $a)))
(= (selectExemplar $metaPop)
    (case $metaPop
        ((NilOS (Error $metaPop (NO_EXEMPLAR)))
        ((ConsOS $x NilOS) $x)
        ($_ (let* (
                    ($probs (getPnScore $metaPop))
                    ($hstScr (List.max >= $probs))
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
(= (sbStreamSelCands NilOS Nil $i) 0)
(= (sbStreamSelCands (ConsOS $x $rest) (Cons $p $ps) $i)
   (let* (
     ((mkExemplar $tree $demeId $cscore $bscore) $x)
     ($_c (py-call (state_builder.add_selection_candidate $i $p $tree)))
   ) (sbStreamSelCands $rest $ps (+ $i 1))))

;; get penalized scores of all the exemplars as a list of Numbers
;;      (ConsOS $x $xs) -- pattern for the list of exemplars constructed by Cons
;;      made use of deconstruction by pattern matching

; (: getPnScore (-> (OS (Exemplar $a)) (List Number)))
(= (getPnScore NilOS) Nil)
(= (getPnScore (ConsOS $x $xs))
   (let (mkExemplar $tree1 $demeId1 (mkCscore $scrr $cpxy $cpxyPen $uniPen $penScr) $bscr1) $x
        (Cons $penScr (getPnScore $xs))))

;;  a function to normalize the score values into normalized scores of Boltzman distribution
;; the function is specific to this distribution type
; (: normalizeProbs (-> Number Number (List Number) (List Number)))
(= (normalizeProbs $invTemp $best Nil) Nil)
(= (normalizeProbs $invTemp $best (Cons $x $xs))
    (let*
        (($new (if (isinf-math $x) 0 (exp (* (- $x $best) $invTemp))))
        ($c (normalizeProbs $invTemp $best $xs)))

        (Cons $new $c)))

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
(= (roulette Nil $sIdx $ajstdsum) (- $sIdx 1))
(= (roulette (Cons $p $xs) $sIdx $ajstdsum)
            (if (<= (- $ajstdsum $p) 0)
            $sIdx
            (roulette $xs (+ 1 $sIdx) (- $ajstdsum $p)))
    )
