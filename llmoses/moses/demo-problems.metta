;; LLMOSES overlay of moses/demo-problems.metta. Import this instead of the
;; upstream file; it imports upstream itself and adds llRunDemoProblem, which
;; calls runMoses with the 15 arguments expected by llmoses/deme/expand-deme.metta.

!(import! &self moses/demo-problems)

;; Maps a demo key to its problem table constructor, called as ($problem).
;; Named llDemoProblem/llRunDemoProblem so they don't add clauses to the
;; upstream demoProblem/runDemoProblem imported above.
(= (llDemoProblem $key)
   (case $key
     ((pa     parity3)
      (dj     disjunction3)
      (maj    majority3)
      (mux    mux3)
      (cp     parity4)
      (annCp  parity4))))

(= (llRunDemoProblem $seed $maxGen $nDeme $fsAlgo $problem)
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
        ($metaPop (cons (mkExemplar (mkTree (mkNode true) ()) (mkDemeId "1") (mkCscore $worstPossibleScore 0 $cpxPen 0 $worstPossibleScore) ($ctor $worstPossibleBScore)) ()))
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
