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
;; A run owns irreversible Python/RNG side effects. Commit to its first result
;; so PeTTa's result enumeration cannot backtrack through completed calls.
(= (runMoses $maxGen $maxScore $maxCandOutput $metaPop $nExpansion $nDeme $context $optimize $nEval $maxCandsPerDeme $minPoolSize $complexityTemperature $nToKeep $capCoef $genCount)
   (once (let* (
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
                   $complexityTemperature $nToKeep $capCoef $genCount))))


;; Four calls within one generation; checkpoint constructors hold native atoms.
;; No constructor below evaluates until llmContinue dispatches it.
(= (runMosesLoop $remaining $total $target $output $mp $exp $nDeme $ctx $opt
                $nEval $maxCands $minimum $trim $keep $cap $legacyGen)
   (if (== $remaining 0)
       (let* (($_terminal (sbEmitTerminal (+ $total 1) $mp)))
         (if (<= $output (OS.length $mp)) (OS.getTopN $output $mp) $mp))
       (let* (
         ($g (+ (- $total $remaining) 1))
         ($_enter (sbEnterGen $g))
         ($_begin (sbBeginGen $g))
         ($_snapshot (sbSnapshotMembers $mp))
         ($frame (mkM2Frame $remaining $total $target $output $mp $exp $nDeme $ctx $opt
                           $nEval $maxCands $minimum $trim $keep $cap $legacyGen $g))
         ($_checkpoint (sbCheckpoint (mkM2Rows $frame)))
         ($_call (py-call (state_builder.call_rows))))
         (llmContinue (mkM2Rows $frame)))))

;; Weight installation changes scalar scores only; cached behavioural vectors survive.
(= (llmRebuildContext) (py-call (state_builder.install_row_weights)))
(= (llmRescoreMetaPop $mp) (llmRescoreInto $mp ()))
(= (llmRescoreInto () $acc) $acc)
(= (llmRescoreInto (cons (mkExemplar $tree $id $cs $bs) $rest) $acc)
   (let* (
     ((mkCscore $raw $complexity $penalty $uniformity $oldPen) $cs)
     ($nativeSum (sumBScore $bs))
     ($weighted (py-call (state_builder.weighted_sum $bs $nativeSum)))
     ($newCs (updatePenalizedScore (mkCscore $weighted $complexity $penalty $uniformity $oldPen) False))
     ($next (OS.insert compareExemplar (mkExemplar $tree $id $newCs $bs) $acc)))
     (llmRescoreInto $rest $next)))

(= (llmContinue (mkM2Rows
       (mkM2Frame $remaining $total $target $output $mp $exp $nDeme $ctx $opt
                  $nEval $maxCands $minimum $trim $keep $cap $legacyGen $g)))
   (let* (
     ($changed (llmRebuildContext))
     ($rescored (if (== $changed 1) (llmRescoreMetaPop $mp) $mp))
     ($_snapshot (sbSnapshotMembers $rescored))
     ($frame (mkM2Frame $remaining $total $target $output $rescored $exp $nDeme $ctx $opt
                       $nEval $maxCands $minimum $trim $keep $cap $legacyGen $g))
     ($_checkpoint (sbCheckpoint (mkM2Exemplar $frame)))
     ($_call (py-call (state_builder.call_exemplar))))
     (llmContinue (mkM2Exemplar $frame))))

(= (llmContinue (mkM2Exemplar
       (mkM2Frame $remaining $total $target $output $mp $exp $nDeme $ctx $opt
                  $nEval $maxCands $minimum $trim $keep $cap $legacyGen $g)))
   (let* (
     ($exemplar (selectExemplar $mp))
     ($tree (getExemplarTree $exemplar))
     ($_selection (sbSetSelection $tree))
     ($frame (mkM2Frame $remaining $total $target $output $mp $exp $nDeme $ctx $opt
                       $nEval $maxCands $minimum $trim $keep $cap $legacyGen $g))
     ($_checkpoint (sbCheckpoint (mkM2Atom $frame $tree)))
     ($_call (py-call (state_builder.call_atom))))
     (llmContinue (mkM2Atom $frame $tree))))

(= (llmExpandSelected $tree $exp $nDeme ($prune $fs $bsc $table) $target $opt)
   (let* (
     ($ids (createDemeIds $exp $nDeme))
     ($demes (createDeme $nDeme $ids $tree $table $fs $prune () mi)))
     (map-atom $demes $deme (expandDemeHelper $deme $bsc $opt))))
(= (llmExpandSelected $tree $exp $nDeme ($games $ratio) $target $opt)
   (let* (
     ($ids (createDemeIds $exp $nDeme))
     ($demes (createDeme $nDeme $ids $tree)))
     (map-atom $demes $deme (expandDemeHelper $deme ($games $ratio $target) $opt))))

(= (llmContinue (mkM2Atom
       (mkM2Frame $remaining $total $target $output $mp $exp $nDeme $ctx $opt
                  $nEval $maxCands $minimum $trim $keep $cap $legacyGen $g) $tree))
   (let* (
     ($optimized (llmExpandSelected $tree $exp $nDeme $ctx $target $opt))
     ;; Force and record every deme before the merge buffer opens.
     ($_demes (map-atom $optimized $deme (sbEmitDeme $g $deme)))
     ($_merge (sbBeginMerge))
     ($scoreContext (case $ctx
         ((($prune $fs $bsc $table) $table) (($games $ratio) $games))))
     ($pool (llmFilterDemes $optimized $nEval $maxCands $minimum $trim
                            $scoreContext $mp $keep $cap $g))
     ($_snapshot (sbSnapshotMembers $pool))
     ($frame (mkM2Frame $remaining $total $target $output $mp $exp $nDeme $ctx $opt
                       $nEval $maxCands $minimum $trim $keep $cap $legacyGen $g))
     ($_checkpoint (sbCheckpoint (mkM2Retention $frame $pool $optimized)))
     ($_call (py-call (state_builder.call_retention $minimum $trim $g))))
     (llmContinue (mkM2Retention $frame $pool $optimized))))

(= (llmContinue (mkM2Retention
       (mkM2Frame $remaining $total $target $output $mp $exp $nDeme $ctx $opt
                  $nEval $maxCands $minimum $trim $keep $cap $legacyGen $g) $pool $optimized))
   (let* (
     ($survivors (llmCommitRetained $pool))
     ($_merged (sbEmitAllMerged $survivors))
     ($_snapshot (sbSnapshotMembers $survivors))
     ($_emit (py-call (state_builder.flush_gen $g)))
     ($empty (== $survivors ()))
     ($topScore (if $empty $target (getExemplarCscore (OS.getByIdx 0 $survivors))))
     ($finished (or $empty (or (== $remaining 1) (== $topScore $target))))
     ($_terminal (if $finished (sbEmitTerminal (+ $g 1) $survivors) 0))
     ($_clear (clearSpace &treeSpace))
     ($_cut (cut)))
     (if $finished
         (if (<= $output (OS.length $survivors)) (OS.getTopN $output $survivors) $survivors)
         (runMosesLoop (- $remaining 1) $total $target $output $survivors $exp $nDeme
                       $ctx $opt $nEval $maxCands $minimum $trim $keep $cap $g))))

;; Define resume only after the dispatcher is known to PeTTa. Defining it in
;; the earlier state-builder import returns (llmContinue ...) as data instead
;; of running the restored continuation. Keep restore and execution inside
;; once so enumerating the public entry point cannot replay side effects.
(= (sbResume)
   (once (let $continuation (py-call (state_builder.restore_checkpoint))
              (llmContinue $continuation))))
