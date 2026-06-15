;; ============================================================================
;; llmoses/moses/demo-problems.metta
;;
;; Overlay for moses/demo-problems.metta — import INSTEAD OF upstream.
;; Fixes runDemoProblem to pass the 15-arg runMoses context tuple expected by
;; llmoses/deme/expand-deme.metta.
;; ============================================================================

!(import! &self moses/demo-problems)

;; Demo keys -> problem table constructors (atoms; invoked as ($problem) at run time).
(= (demoProblem $key)
   (case $key
     ((pa     parity3)
      (dj     disjunction3)
      (maj    majority3)
      (mux    mux3)
      (cp     parity4)
      (annCp  parity4))))

(= (runDemoProblem $seed $maxGen $nDeme $fsAlgo $problem)
   (let*
      (
        ($srp (py-call (random.seed $seed)))
        ($cpxPen 3.5)
        ($capCoef 50)
        ($complexityTemperature 6)
        ($truthTableBScore (createTruthTableBScore $cpxPen ($problem)))
        (($ctor $worstPossibleBScore) (worstPossibleScore $truthTableBScore))
        ($worstPossibleScore (List.sum $worstPossibleBScore))
        ($bestPosssibleCscore (getBestPossibleCscore $cpxPen $problem))
        ($_ (println! (BestPossibleScore: $bestPosssibleCscore)))
        ($metaPop (ConsOS (mkExemplar (mkTree (mkNode true) Nil) (mkDemeId "1") (mkCscore $worstPossibleScore 0 $cpxPen 0 $worstPossibleScore) ($ctor $worstPossibleBScore)) NilOS))
        ($result (runMoses $maxGen $bestPosssibleCscore 10 $metaPop 0 $nDeme
              (False $fsAlgo $truthTableBScore ($problem))
              hillClimbing
              10000 100 20 $complexityTemperature
              50 $capCoef $maxGen))
        ($_ (println! (Result: $result)))
        ($newR (osToExpression (mapG cleanedExemplar $result) ()))
        ($_ (cut))
      )
      (FinalResult $newR)))
