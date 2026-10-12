;; LLMOSES state-builder wrapper: MeTTa entry points for utilities/state_builder.py.
;; Load after extractors.metta. Bind extractor results with eval before passing
;; them to py-call; otherwise they can reach Python unevaluated.

!(import! &self "state_builder.py")

;; Prints the run directory on import, confirming state_builder.py was found on PYTHONPATH.
!(py-call (state_builder.sb_run_dir))

;; direct calls; arguments are already plain values
(= (sbNewRun)           (py-call (state_builder.new_run)))
(= (sbBeginGen $g)      (py-call (state_builder.begin_gen $g)))
(= (sbGetTotalEvals)    (py-call (state_builder.get_total_evals)))
(= (sbEnterGen $g) (py-call (state_builder.enter_gen $g)))
(= (sbCheckpoint $continuation) (py-call (state_builder.checkpoint_native $continuation)))
;; sbResume lives in llmoses/deme/expand-deme.metta, after llmContinue; defined
;; here, PeTTa would treat (llmContinue ...) as data.
(= (sbSnapshotMembers $mp)
   (let* (($g (py-call (state_builder.current_generation)))
          ($_clear (py-call (state_builder.clear_members $g)))
          ($_members (sbEmitAllMembers $g $mp))) 0))

;; records the input feature labels from the ITable, once per boolean run
(= (sbSetProblemSpec $itable)
   (let* (($labels (eval (getArgLabels $itable))))
     (py-call (state_builder.set_problem_spec $labels))))

;; records the selected exemplar. Pass the full tree so its program_id matches the member's.
(= (sbSetSelection $tree)
   (py-call (state_builder.set_selection $tree)))

;; sends each metapopulation member to state_builder.add_member
;; $expr is the preOrder form for display; $tree is the full tree, used for the program_id.
(= (sbEmitMembers $g $os $i $n)
   (if (>= $i $n)
       0
       (let* (
         ($x    (memberByIdx $os $i))
         ($expr (eval (memberExpr   $x)))
         ($tree (eval (memberTree   $x)))
         ($cs   (eval (cscoreFields (memberCscore $x))))
         ($bs   (eval (memberBScore $x)))
         ($_    (py-call (state_builder.add_member $g $expr $tree $cs $bs)))
       )
       (sbEmitMembers $g $os (+ $i 1) $n))))
(= (sbEmitAllMembers $g $os)
   (let* (($n (eval (metapopSize $os)))) (sbEmitMembers $g $os 0 $n)))

;; sends a deme's knobs, tree and instance count to state_builder, keyed by $demeId
(= (sbEmitDemeKnobs $g $demeId ()) 0)
(= (sbEmitDemeKnobs $g $demeId (cons $k $rest))
   (let* (
     ($loc (eval (knobLoc $k))) ($mul (eval (knobMultip $k)))
     ($def (eval (knobDefault $k))) ($tag (eval (knobTag $k)))
     ($_k  (py-call (state_builder.add_knob $g $demeId $loc $mul $def $tag)))
   ) (sbEmitDemeKnobs $g $demeId $rest)))

(= (sbEmitDeme $g $deme)
   (let* (
     ((mkDeme $rep $sInst $demeId) $deme)
     ($inst (eval (List.length (second $sInst))))
     ($knobs (eval (knobsOfRep $rep)))
     ($_k   (sbEmitDemeKnobs $g $demeId $knobs))
     ($tr   (eval (repTree $rep)))
     ($_s   (py-call (state_builder.set_deme $g $demeId $tr $inst)))
   ) 0))

;; run parameters, stored in Python until the next new_run and reused by
;; flush_gen and flush_terminal
(= (sbSetRunParam $name $value)
   (py-call (state_builder.set_run_param $name $value)))

(= (sbSetRunParams $problemType $complexityRatio $maxGen $nEval $maxCandsPerDeme
                   $minPoolSize $complexityTemperature $nToKeep $capCoef $nDeme $optimizer
                   $hillClimbMaxEvals)
   (let* (
     ($_p1  (sbSetRunParam "problem_type" $problemType))
     ($_p2  (sbSetRunParam "complexity_ratio" $complexityRatio))
     ($_p3  (sbSetRunParam "max_gen" $maxGen))
     ($_p4  (sbSetRunParam "n_eval" $nEval))
     ($_p5  (sbSetRunParam "max_cands_per_deme" $maxCandsPerDeme))
     ($_p6  (sbSetRunParam "min_pool_size" $minPoolSize))
     ($_p7  (sbSetRunParam "complexity_temperature" $complexityTemperature))
     ($_p8  (sbSetRunParam "n_to_keep" $nToKeep))
     ($_p9  (sbSetRunParam "cap_coef" $capCoef))
     ($_p10 (sbSetRunParam "n_deme" $nDeme))
     ($_p11 (sbSetRunParam "optimizer" $optimizer))
     ($_p12 (sbSetRunParam "hill_climb_max_evaluations" $hillClimbMaxEvals))
   ) 0))

;; sbBeginMerge must be called before merging so set_merge_count and
;; sbEmitCullCands have a merge record to write to.
(= (sbBeginMerge) (py-call (state_builder.begin_merge)))

;; writes the run configuration, before generation 1
(= (sbEmitRunConfig) (py-call (state_builder.emit_run_config)))

;; records the candidates that survived dominance filtering in merge-demes.
;; Score fields are extracted one by one so they reach Python as numbers, not as an mkCscore atom.
(= (sbEmitCullCands ()) 0)
(= (sbEmitCullCands (cons $ex $rest))
   (let* (
     ($tree   (eval (getExemplarTree   $ex)))
     ($expr   (eval (preOrder $tree)))
     ($bscore (eval (getExemplarBScore  $ex)))
     ($cscore (eval (getExemplarCscore  $ex)))
     ($raw    (eval (getScore    $cscore)))
     ($cpx    (eval (getComp     $cscore)))
     ($pen    (eval (getPenScore $cscore)))
     ($_ (py-call (state_builder.add_cull_candidate $expr $tree $bscore $raw $cpx $pen)))
   ) (sbEmitCullCands $rest)))

;; records the tree of each member of the merged metapopulation
(= (sbEmitMergedPop $os $i $n)
   (if (>= $i $n) 0
       (let* (($x  (memberByIdx $os $i))
              ($tr (eval (memberTree $x)))
              ($_  (py-call (state_builder.add_merged_member $tr))))
         (sbEmitMergedPop $os (+ $i 1) $n))))
(= (sbEmitAllMerged $os)
   (let* (($n (eval (metapopSize $os))))
     (sbEmitMergedPop $os 0 $n)))

;; emits a whole generation in one call: members, every optimized deme, then flush_gen.
;; Requires sbSetRunParams to have been called for the run.
(= (sbEmitGeneration $g $metaPop $optimizedDemes)
   (let* (
     ($_g1 (sbBeginGen $g))
     ($_g2 (sbEmitAllMembers $g $metaPop))
     ($_g3 (let $r (map-atom $optimizedDemes $deme (sbEmitDeme $g $deme)) 0))
     ($_g4 (py-call (state_builder.flush_gen $g)))
   ) 0))

;; writes the final metapopulation to terminal.json. No ready file is written
;; for it. Requires sbSetRunParams to have been called for the run.
(= (sbEmitTerminal $g $metaPop)
   (let* (
     ($_t1 (sbBeginGen $g))
     ($_t2 (sbEmitAllMembers $g $metaPop))
     ($_t3 (py-call (state_builder.flush_terminal $g)))
   ) 0))

;; records the strategy problem. Upstream scores against a mix of random and
;; minimax opponents, so the opponent is recorded as mixed-opponents.
(= (sbSetProblemSpecStrategy $nGames $complexityRatio)
   (let* (($moves (eval (getAllGameMoves))))
     (py-call (state_builder.set_problem_spec_strategy $moves $nGames mixed-opponents $complexityRatio))))

;; starts a boolean run: new_run, problem spec, run parameters, run config.
;; For the context ($prune $fsAlgo $truthTableBScore $itable).
(= (sbBeginRunBoolean
      $maxGen $nEval $maxCandsPerDeme $minPoolSize $complexityTemperature
      $nToKeep $capCoef $nDeme
      $truthTableBScore $itable)
   (let* (
     (($cpxCoeff $_size $_tbl) (eval (getTTableParams $truthTableBScore)))
     ($_0 (sbNewRun))
     ($_1 (sbSetProblemSpec $itable))
     ($_2 (sbSetRunParams
             "boolean" $cpxCoeff
             $maxGen $nEval $maxCandsPerDeme
             $minPoolSize $complexityTemperature
             $nToKeep $capCoef $nDeme "hillClimbing"
             500))
     ($_3 (sbEmitRunConfig))
   ) 0))

;; starts a strategy run, as above. For the context ($nGames $complexityRatio).
(= (sbBeginRunStrategy
      $maxGen $nEval $maxCandsPerDeme $minPoolSize $complexityTemperature
      $nToKeep $capCoef $nDeme
      $nGames $complexityRatio)
   (let* (
     ($_0 (sbNewRun))
     ($_1 (sbSetProblemSpecStrategy $nGames $complexityRatio))
     ($_2 (sbSetRunParams
             "strategy" $complexityRatio
             $maxGen $nEval $maxCandsPerDeme
             $minPoolSize $complexityTemperature
             $nToKeep $capCoef $nDeme "hillClimbing"
             500))
     ($_3 (sbEmitRunConfig))
   ) 0))
