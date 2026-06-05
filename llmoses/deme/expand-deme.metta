(= (createInitialInstance $dscMp)
   (let* (
     ($knobs (MultiMap.values $dscMp))
     ($defaults (List.map getKnobDefault $knobs))
   )
   $defaults))

;; Recursively optimizes each deme in a list using the provided optimizer function.
;; Params:
;;   (List Deme): The list of demes to optimize.
;;   $context: The scoring context - either TruthTableBScore or tuple ($nGames $opponentPolicy)
;;   $inst: The initial instance for optimization.
;;   $optimize: The optimizer function to apply to each deme.
;;  Returns: (List Deme): A new list where each deme has been optimized.
; (: optimizeDemes (-> (List Deme) $context Instance $optimize (Instance Deme $state)))
;; Game strategy version - unpacks tuple with target score
;; Strategy version - unpacks game parameters and calls hillClimbing with mkParams
(= (optimizeDemes $deme ($nGames $opponentPolicy $complexityRatio $targetCScore) $inst $optimize)
   ($optimize $deme $targetCScore $inst (mkParams applyStrategyBasedScore ($nGames $opponentPolicy $complexityRatio))))
;; Boolean version - passes context as-is
(= (optimizeDemes $deme $context $inst $optimize)
   ($optimize $deme $context $inst))

;; Extracts default specification from a knob
; (: getKnobDefault (-> $knob Number))
(= (getKnobDefault (mkLSK (mkDiscKnob $knob $multip $curr (mkDiscSpec $def) $dis))) $def)
(= (getKnobDefault (mkSSK (mkDiscKnob $knob $multip $curr (mkDiscSpec $def) $dis))) $def)

;; Runs one deme-creation and optimization step, then merges the optimized deme into the metapopulation.
;; Params:
;;   $metaPop: The current metapopulation.
;;   $nExpansion: Expansion count or deme index.
;;   $nDeme: Number of demes to create.
;;   $truthTableBScore: TruthTableBScore
;;   $optimize: Optimizer function (e.g., hill climbing).
;;   $nEval: Maximum number of evaluations.
;;   $maxCandsPerDeme: Maximum candidates per deme.
;;   $minPoolSize: Minimum deme size to retain.
;;   $complexityTemperature: Parameter for score range in trimming.
;;   $itable: The input table.
;;   $nToKeep: Target size for resized metapopulation.
;;   $capCoef: Capacity coefficient for resizing.
;;   $genCount: Generation count for resizing.
;; Returns:
   ;;   $updatedMetaPop: Updated metapopulation with the new optimized deme merged in.
; (: expandDeme (-> (OS (Exemplar $a)) Number Number Bool Symbol (TruthTableBScore $a) (-> Deme (TruthTableBScore $a) Instance $Scorer (Instance Deme $state)) $Scorer Number Number Number Number (ITable $a) Number Number Number (OS (Exemplar $a))))
(= (expandDeme $metaPop $nExpansion $nDeme $prune-exemplar $fs-algo $truthTableBScore $optimize $itable $scorerType)
(let*
   (
    ;; ($_ (println! ""))
    ;; ($_ (println! (MetaPop: $metaPop)))
    ;; ($_ (println! "Selecting Exemplar"))
    ($exemplar (selectExemplar $metaPop))
    ;; ($_ (println! $exemplar))
    ;; ($_ (println! "getting exemplar tree"))
    ($tree (getExemplarTree $exemplar)) 
    ($_ (println! (SelectedTree: (preOrder $tree))))
    ($_ (sbSetSelection $tree))                          ;; <-- LLMOSES post_selection hook
    ;; ($_ (println! "creating deme IDs"))
    ($demeIds (createDemeIds $nExpansion $nDeme))
    ;; ($_ (println! $demeIds))
    ; ($argLabels (getArgLabels $itable))
    ;; ($_ (println! "Creating Deme"))
    ($demes (createDeme $nDeme $demeIds $tree $itable $fs-algo $prune-exemplar () $scorerType))
    )
    (map-atom $demes $deme (expandDemeHelper $deme $truthTableBScore $optimize))
   ))

;; Overloaded version for game strategy domain - 8 parameters
(= (expandDeme $metaPop $nExpansion $nDeme $nGames $opponentPolicy $complexityRatio $targetCScore $optimize)
   (let*
      (
         ($exemplar (trace! "Selecting Exemplar" (selectExemplar $metaPop)))
         ($tree (trace! "getting exemplar tree" (getExemplarTree $exemplar)))
         ($demeIds (trace! "creating deme IDs" (createDemeIds $nExpansion $nDeme)))
         ($demes (trace! "Creating Deme" (createDeme $nDeme $demeIds $tree)))
         ($gameContext ($nGames $opponentPolicy $complexityRatio $targetCScore))
      )
      (map-atom $demes $deme (expandDemeHelper $deme $gameContext $optimize))))

;; Unified helper for both Boolean and Strategy domains
;; Optimizes each deme in the list using the provided optimizer and context
;; Params:
;;   $deme: Deme to optimize
;;   $context: Scoring context (ITable for Boolean, tuple for Strategy)
;;   $optimize: Optimizer function
;; Returns: Optimized deme with scored instances
(= (expandDemeHelper (mkDeme (mkRep (mkKbMap (mkDscKbMp $dscKbMp) (mkDscMp $dscMp)) $updatedTree) $sInstList $demeId) $context $optimize)
(let*
(
    ($lengthOfDscKbMp (Map.length $dscKbMp))
    ;; ($generatedList (List.generate $lengthOfDscKbMp 0))
    ($generatedList (createInitialInstance $dscMp))
    ($deme (mkDeme (mkRep (mkKbMap (mkDscKbMp $dscKbMp) (mkDscMp $dscMp)) $updatedTree) $sInstList $demeId))
    ;; ($_ (println! (Rep: (mkRep (mkKbMap (mkDscKbMp $dscKbMp) (mkDscMp $dscMp)) $updatedTree))))
    ;; ($_ (println! "Optimizing Deme"))
    (($inst $optimDeme $state) (optimizeDemes $deme $context (mkInst $generatedList) $optimize))
    ($_ (py-call (state_builder.set_deme_evals $demeId (index-atom $state 8))))   ;; <-- per-deme fitness-call count
)
$optimDeme
))
;; The main loop 
;; Takes 2 termination criterias:
;;     - $maxGen : how many times we want the loop to run
;;     - $maxScore : the maximum score we want the top Examplar to have
;; It also takes:
;;     - $maxCandOutput : The number of candidates to be returned
;;     - other parameters required by the expandDeme method
; (: runMoses (-> Number Cscore Number (OS (Exemplar $a)) Number Number Bool Symbol (TruthTableBScore $a) (-> Deme (TruthTableBScore $a) Instance $Scorer (Instance Deme $state)) $Scorer Number Number Number Number (ITable $a) Number Number Number (OS (Exemplar $a))))
;; Public entry — unchanged 15-arg signature. Captures the budget once,
;; then delegates to the internal loop with $totalGen pinned.
(= (runMoses $maxGen $maxScore $maxCandOutput $metaPop $nExpansion $nDeme $context $optimize $nEval $maxCandsPerDeme $minPoolSize $complexityTemperature $nToKeep $capCoef $genCount)
   (let* (($totalGen $maxGen)
          ($_ (sbNewRun))
          ($_ (case $context
                ((($pe $fs $ttbs $itable) (sbSetProblemSpec $itable))
                 ($_ 0)))))
        (runMosesLoop $maxGen $totalGen $maxScore $maxCandOutput $metaPop $nExpansion $nDeme $context $optimize $nEval $maxCandsPerDeme $minPoolSize $complexityTemperature $nToKeep $capCoef $genCount)))

;; Internal loop — carries $totalGen (the original budget, never modified) so
;; the ascending generation index can be derived at each step.
(= (runMosesLoop $maxGen $totalGen $maxScore $maxCandOutput $metaPop $nExpansion $nDeme $context $optimize $nEval $maxCandsPerDeme $minPoolSize $complexityTemperature $nToKeep $capCoef $genCount)
(if (== $maxGen 0)
    (if (<= $maxCandOutput (OS.length $metaPop))
        (let $topCandidates (OS.getTopN $maxCandOutput $metaPop) $topCandidates)
        $metaPop
  )
    (let*
     (
       ($_ (println! (Generation $maxGen)))
       ($genIndex (+ (- $totalGen $maxGen) 1))
       ($optimizedDemes (case $context
                        ((($prune-exemplar $fs-algo $truthTableBScore $itable) (trace! "expand  deme returnn" (expandDeme $metaPop $nExpansion $nDeme $prune-exemplar $fs-algo $truthTableBScore $optimize $itable mi)))
                        (($nGames $opponentPolicy $complexityRatio) (trace! "expand deme return" (expandDeme $metaPop $nExpansion $nDeme $nGames $opponentPolicy $complexityRatio $maxScore $optimize))))))
       ($_ (sbBeginMerge))                                   ;; <-- open merge buffer BEFORE mergeDemes
       ($updatedMetaPop (case $context 
                        ((($prune-exemplar $fs-algo $truthTableBScore $itable) (trace! "Merging Deme" (mergeDemes $optimizedDemes $nEval $maxCandsPerDeme $minPoolSize $complexityTemperature $itable $metaPop $nToKeep $capCoef $genCount)))
                        (($nGames $opponentPolicy $complexityRatio) (trace! "Merging Deme" (mergeDemes $optimizedDemes $nEval $maxCandsPerDeme $minPoolSize $complexityTemperature ($nGames $opponentPolicy) $metaPop $nToKeep $capCoef $genCount))))))
       ;; ($_ (println! (Updated MetaPop: $updatedMetaPop)))
       ($top (OS.getByIdx 0 $metaPop))
       ;; ($_ (println! (Top Exemplar before expansion: $top)))
       ($topScore (getExemplarCscore $top))
       ;; ($_ (println! (topscore: $topScore)))
       ;; --- LLMOSES: per-context emit params, then full state-builder emit ---
       ;; complexity_ratio exists ONLY on the game/strategy context (its 3-tuple).
       ;; The boolean 4-tuple context has no such parameter, so it emits () —
       ;; absent, not a fabricated default — keeping captured state honest.
       (($problemType $complexityRatio)
          (case $context
            ((($prune-exemplar $fs-algo $truthTableBScore $itable) ("boolean" ()))
             (($nGames $opponentPolicy $cr)                        ("strategy" $cr)))))
       ;; emit per-candidate neighborhood size before flush_gen consumes it
       ($_ (case $context
             ((($prune-exemplar $fs-algo $truthTableBScore $itable)
               (sbEmitAllMemberNbh $metaPop $itable mi))
              (($nGames $opponentPolicy $cr) 0))))
       ($_ (sbEmitAllMerged $updatedMetaPop))
       ($_ (sbEmitGeneration $genIndex $metaPop $optimizedDemes
                             $problemType $complexityRatio $maxGen $nEval $maxCandsPerDeme
                             $minPoolSize $complexityTemperature $nToKeep $capCoef $nDeme $optimize))
       ($_ (if (== $maxGen 1)
               (sbEmitTerminal (+ $genIndex 1) $updatedMetaPop $problemType $complexityRatio
                               $maxGen $nEval $maxCandsPerDeme $minPoolSize $complexityTemperature
                               $nToKeep $capCoef $nDeme $optimize)
               0))
       ;; ---------------------------------------------------------------------
       ($resultCandi (if (<= $maxCandOutput (OS.length $updatedMetaPop)) (OS.getTopN $maxCandOutput $updatedMetaPop) $updatedMetaPop))
       ($_ (cut))
       ($_ (println! ""))
      )
 (if (== $topScore $maxScore)
         $resultCandi
         (runMosesLoop (- $maxGen 1) $totalGen $maxScore $maxCandOutput $updatedMetaPop $nExpansion $nDeme $context $optimize $nEval $maxCandsPerDeme $minPoolSize $complexityTemperature $nToKeep $capCoef $genCount)))))


;; Some helpers specific to final testing
(= (mapG $f NilOS) NilOS)
(= (mapG $f Nil) Nil)
(= (mapG $f ($ctor $x $xs)) ($ctor ($f $x) (mapG $f $xs)))

(= (printExemplar (mkExemplar $tree $demeId $cscore $bscore)) (println! (Tree: (preOrder $tree) CScore: $cscore Bscore: $bscore)))
(= (cleanedExemplar (mkExemplar $tree $demeId $cscore (mkBScore $bscore))) ((preOrder $tree) (List.sum $bscore)))

(= (printInstance (mkInst $inst)) (println! (List.listToExpr $inst)))
