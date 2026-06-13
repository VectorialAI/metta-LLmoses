;; ============================================================================
;; llmoses/scoring/regression-bscore.metta
;;
;; Behavioral scorer for the regression (contin) problem type.
;;
;; mkRegressionBScore deliberately mirrors mkTruthTableBScore's 3-field shape
;; (scoring/bscore.metta L41-47): complexity ratio, table size, ITable —
;; so the cscore/complexity-scorer plumbing transfers unchanged. The tagged
;; constructor head also makes every regression dispatch site unambiguous
;; against boolean (mkITable capture) and strategy (tuple catch-all) arms.
;;
;; Per-row score is -(prediction - target)^2 — contin_bscore::operator() in
;; asmoses bscores.cc (squared-error variant), so exact fit = all-zeros bscore.
;; ============================================================================

;; Per-run memoization cache, mirroring &bscoreCache / &strategyScoreCache.
!(bind! &regressionScoreCache (new-space))

;; (: RegressionBScore Type)
;; (: mkRegressionBScore (-> Number Number (ITable Number) RegressionBScore))

;; Constructor that derives the table size, mirroring createTruthTableBScore.
;; (: createRegressionBScore (-> Number (ITable Number) RegressionBScore))
(= (createRegressionBScore $complexityRatio (mkITable $rows $labels))
   (mkRegressionBScore $complexityRatio (List.length $rows) (mkITable $rows $labels)))

;; Field accessors.
(= (getRegressionTable (mkRegressionBScore $compRatio $size $table)) $table)
(= (getRegressionRatio (mkRegressionBScore $compRatio $size $table)) $compRatio)

;; Best/worst possible BehavioralScore — same contract as the boolean pair.
;; Worst uses a large negative sentinel since squared error is unbounded.
(= (bestPossibleScore (mkRegressionBScore $compRatio $size $table))
   (mkBScore (List.repeat $size 0)))
(= (worstPossibleScore (mkRegressionBScore $compRatio $size $table))
   (mkBScore (List.repeat $size (* -1 (pow-math 10 100)))))

;; Score one row: split inputs from the trailing target column, evaluate the
;; preOrder expression, return the negated squared error.
;; (: regressionRowScore (-> Expression (List Symbol) (List Number) Number))
(= (regressionRowScore $expr $inputLabels $row)
   (let* (
     ($nCols (List.length $row))
     ($inputs (List.takeN (- $nCols 1) $row))
     ($target (List.getByIdx $row (- $nCols 1)))
     ($pairs (List.zip $inputLabels $inputs))
     ($pred (evalNumeric $expr $pairs))
     ($err (- $pred $target))
   )
   (* -1 (* $err $err))))

;; Map regressionRowScore over the row list (explicit recursion; no curry).
;; (: regressionRowScores (-> Expression (List Symbol) (List (List Number)) (List Number)))
(= (regressionRowScores $expr $inputLabels Nil) Nil)
(= (regressionRowScores $expr $inputLabels (Cons $row $rest))
   (Cons (regressionRowScore $expr $inputLabels $row)
         (regressionRowScores $expr $inputLabels $rest)))

;; Behavioral score for a contin tree over a numeric ITable, with caching —
;; the regression analog of scoreTree (scoring/bscore.metta L62-81).
;; Cache key is (scoring context, tree) so one tree evaluated against
;; multiple tables cannot cross-poison entries.
;; (: scoreTreeRegression (-> (ITable Number) (Tree $a) Space BehavioralScore))
(= (scoreTreeRegression (mkITable $rows $labels) $tree $cacheSpace)
   (let $ctx (mkITable $rows $labels)
     (chain (collapse (match $cacheSpace ($ctx $tree $bscore) $bscore)) $val
       (if (== $val ())
           (let* (
             ($expr (preOrder $tree))
             ($inputLabels (List.takeN (- (List.length $labels) 1) $labels))
             ($scores (regressionRowScores $expr $inputLabels $rows))
             ($result (mkBScore $scores))
             ($_ (add-atom $cacheSpace ($ctx $tree $result)))
           )
           $result)
           (car-atom $val)))))
