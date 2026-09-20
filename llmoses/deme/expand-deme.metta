;; LLMOSES overlay of deme/expand-deme.metta.
;; The evolutionary flow and representation shapes follow upstream; hooks here
;; open and flush the state/action emission lifecycle around each generation.

;; WARN: This code might be generating knobs out of order. Check if the knob map returned from the representation building preserves the order of knob creation.
(= (createInitialInstance $dscMp)
   (let* (
          ($knobs (Map.values $dscMp))
          ($defaults (List.map getKnobDefault $knobs))
          ($finalDefaults (List.map second $defaults))
         )
         $finalDefaults))

;; Recursively optimizes each deme in a list using the provided optimizer function.
;; Params:
;;   (List Deme): The list of demes to optimize.
;;   $context: The scoring context - either TruthTableBScore or ($nGames $complexityRatio)
;;   $inst: The initial instance for optimization.
;;   $optimize: The optimizer function to apply to each deme.
;;  Returns: (List Deme): A new list where each deme has been optimized.
; (: optimizeDemes (-> (List Deme) $context Instance $optimize (Instance Deme $state)))
;; Game strategy version - unpacks tuple with target score
;; Strategy version - unpacks game parameters and calls hillClimbing with mkParams
(= (optimizeDemes $deme ($nGames $complexityRatio $targetCScore) $inst $optimize)
   ($optimize $deme $targetCScore $inst (mkParams applyStrategyBasedScore ($nGames $complexityRatio))))
;; Boolean version - passes context as-is
(= (optimizeDemes $deme $context $inst $optimize)
   ($optimize $deme $context $inst))

;; Extracts default specification from a knob
; (: getKnobDefault (-> $knob Number))
;; (= (getKnobDefault (mkLSK (mkDiscKnob $multip $curr (mkDiscSpec $def) $dis))) $def)
;; (= (getKnobDefault (mkSSK (mkDiscKnob $knob $multip $curr (mkDiscSpec $def) $dis))) $def)

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
    ($_ (sbSetSelection $tree))
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
(= (expandDeme $metaPop $nExpansion $nDeme $nGames $complexityRatio $targetCScore $optimize)
   (let*
      (
         ($exemplar (trace! "Selecting Exemplar" (selectExemplar $metaPop)))
         ($tree (trace! "getting exemplar tree" (getExemplarTree $exemplar)))
         ($_ (sbSetSelection $tree))
         ($demeIds (trace! "creating deme IDs" (createDemeIds $nExpansion $nDeme)))
         ($demes (trace! "Creating Deme" (createDeme $nDeme $demeIds $tree)))
         ($gameContext ($nGames $complexityRatio $targetCScore))
      )
      (map-atom $demes $deme (expandDemeHelper $deme $gameContext $optimize))))

;; Unified helper for both Boolean and Strategy domains
;; Optimizes each deme in the list using the provided optimizer and context
;; Params:
;;   $deme: Deme to optimize
;;   $context: Scoring context (ITable for Boolean, tuple for Strategy)
;;   $optimize: Optimizer function
;; Returns: Optimized deme with scored instances
(= (expandDemeHelper (mkDeme (mkRep (mkKbMap (mkDscMp $dscKbMp)) $updatedTree) $sInstList $demeId) $context $optimize)
(let*
(
    ($lengthOfDscKbMp (Map.length $dscKbMp))
    ;; ($generatedList (List.generate $lengthOfDscKbMp 0))
    ($generatedList (createInitialInstance $dscKbMp))
    ($_ (println! (GeneratedList: $generatedList)))
    ($deme (mkDeme (mkRep (mkKbMap (mkDscMp $dscKbMp)) $updatedTree) $sInstList $demeId))
    ;; ($_ (println! (Rep: (mkRep (mkKbMap (mkDscKbMp $dscKbMp) (mkDscMp $dscMp)) $updatedTree))))
    ;; ($_ (println! "Optimizing Deme"))
    (($inst $optimDeme $state) (optimizeDemes $deme $context (mkInst $generatedList) $optimize))
    ($_ (py-call (state_builder.set_deme_evals $demeId $state)))
)
$optimDeme
))

;; Upstream's strategy builder still carries the legacy two-field KnobMap
;; while boolean/disc-probe representations use the new single DiscMap shape.
(= (expandDemeHelper (mkDeme (mkRep (mkKbMap $dscKbMp (mkDscMp $dscMp)) $updatedTree) $sInstList $demeId) $context $optimize)
(let*
(
    ($generatedList (createInitialInstance $dscMp))
    ($deme (mkDeme (mkRep (mkKbMap $dscKbMp (mkDscMp $dscMp)) $updatedTree) $sInstList $demeId))
    (($inst $optimDeme $state) (optimizeDemes $deme $context (mkInst $generatedList) $optimize))
    ($_ (py-call (state_builder.set_deme_evals $demeId $state)))
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
;; Public entry: initialize one LLMOSES run, then keep the original generation
;; budget pinned so emitted generations count upward while MOSES counts down.
(= (runMoses $maxGen $maxScore $maxCandOutput $metaPop $nExpansion $nDeme $context $optimize $nEval $maxCandsPerDeme $minPoolSize $complexityTemperature $nToKeep $capCoef $genCount)
   (let* (
     ($_ (case $context
           ((($prune-exemplar $fs-algo $truthTableBScore $itable)
             (sbBeginRunBoolean
               $maxGen $nEval $maxCandsPerDeme $minPoolSize $complexityTemperature
               $nToKeep $capCoef $nDeme $truthTableBScore $itable))
            (($nGames $complexityRatio)
             (sbBeginRunStrategy
               $maxGen $nEval $maxCandsPerDeme $minPoolSize $complexityTemperature
               $nToKeep $capCoef $nDeme $nGames $complexityRatio))
            ($_x 0)))))
     (runMosesLoop $maxGen $maxGen $maxScore $maxCandOutput $metaPop $nExpansion $nDeme
                   $context $optimize $nEval $maxCandsPerDeme $minPoolSize
                   $complexityTemperature $nToKeep $capCoef $genCount)))

;; Phase II lever 4 rebuilds the scoring context with a new complexity ratio.
(= (llmRebuildContext $ctx $newRatio)
   (case $ctx
     ((($pe $fs (mkTruthTableBScore $cr $size $tbl) $itable)
        ($pe $fs (mkTruthTableBScore $newRatio $size $tbl) $itable))
      (($nGames $cr) ($nGames $newRatio))
      ($other $other))))

(= (runMosesLoop $maxGen $totalGen $maxScore $maxCandOutput $metaPop $nExpansion $nDeme $context $optimize $nEval $maxCandsPerDeme $minPoolSize $complexityTemperature $nToKeep $capCoef $genCount)
   (if (== $maxGen 0)
       (if (<= $maxCandOutput (OS.length $metaPop))
           (OS.getTopN $maxCandOutput $metaPop)
           $metaPop)
       (let* (
         ($_ (println! (Generation $maxGen)))
         ($genIndex (+ (- $totalGen $maxGen) 1))
         ($_fence (sbEnterGen $genIndex))
         ($_ulog (sbLogUtilities $genIndex))
         ($ratioOverride (py-call (state_builder.current_complexity_ratio $genIndex)))
         ($ctx2 (if (== $ratioOverride 0) $context (llmRebuildContext $context $ratioOverride)))
         ($cmpOn (py-call (state_builder.comparator_resort_active)))
         ($mp2 (if (== $cmpOn 1) (llmResortMetapop $metaPop) $metaPop))
         ($optimizedDemes
           (case $ctx2
             ((($prune-exemplar $fs-algo $truthTableBScore $itable)
               (trace! "expand  deme returnn"
                 (expandDeme $mp2 $nExpansion $nDeme $prune-exemplar $fs-algo
                             $truthTableBScore $optimize $itable mi)))
              (($nGames $complexityRatio)
              (trace! "expand deme return"
                 (expandDeme $mp2 $nExpansion $nDeme $nGames $complexityRatio
                             $maxScore $optimize))))))
         ;; Force expansion before opening the merge buffer without requiring
         ;; the optimized-deme list to contain exactly one element.
         ((mkDeme $rep $sInst $demeId) (car-atom $optimizedDemes))
         ($_ (println! (FirstOptimizedDeme: (List.length (second $sInst)))))
         ($_ (sbBeginMerge))
         ($updatedMetaPop
           (case $ctx2
             ((($prune-exemplar $fs-algo $truthTableBScore $itable)
               (trace! "Merging Deme"
                 (mergeDemes $optimizedDemes $nEval $maxCandsPerDeme $minPoolSize
                             $complexityTemperature $itable $mp2 $nToKeep $capCoef $genCount)))
              (($nGames $complexityRatio)
               (trace! "Merging Deme"
                 (mergeDemes $optimizedDemes $nEval $maxCandsPerDeme $minPoolSize
                             $complexityTemperature $nGames $mp2 $nToKeep $capCoef $genCount))))))
         ($top (OS.getByIdx 0 $mp2))
         ($topScore (getExemplarCscore $top))
         ($_ (sbEmitAllMerged $updatedMetaPop))
         ($_emit (sbEmitGeneration $genIndex $mp2 $optimizedDemes))
         ($_resp (sbAwaitResponse $genIndex))
         ($_term (if (or (== $maxGen 1) (== $topScore $maxScore))
                     (sbEmitTerminal (+ $genIndex 1) $updatedMetaPop)
                     0))
         ($resultCandi (if (<= $maxCandOutput (OS.length $updatedMetaPop))
                           (OS.getTopN $maxCandOutput $updatedMetaPop)
                           $updatedMetaPop))
         ($nothing (clearSpace &treeSpace))
         ($_ (cut))
         ($_ (println! ""))
       )
       (if (== $topScore $maxScore)
           $resultCandi
           (runMosesLoop (- $maxGen 1) $totalGen $maxScore $maxCandOutput $updatedMetaPop
                         $nExpansion $nDeme $ctx2 $optimize $nEval $maxCandsPerDeme
                         $minPoolSize $complexityTemperature $nToKeep $capCoef $genCount)))))



;; Some helpers specific to final testing
(= (mapG $f $xs) (map-atom $xs $f))

(= (printExemplar (mkExemplar $tree $demeId $cscore $bscore)) (println! (Tree: (preOrder $tree) CScore: $cscore Bscore: $bscore)))
(= (cleanedExemplar (mkExemplar $tree $demeId $cscore (mkBScore $bscore))) ((preOrder $tree) (List.sum $bscore)))

(= (printInstance (mkInst $inst)) (println! (List.listToExpr $inst)))
