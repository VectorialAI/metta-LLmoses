;; ============================================================================
;; llmoses/wrapper/state-builder.metta  (v0.4-mvp)
;;
;; Mirrors state-emitter.metta's emitGen call site EXACTLY (expand-deme.metta
;; lines 145-148): bind each value with `eval` in the let*, THEN pass the bound
;; bare variable to py-call. NEVER pass an extractor CALL directly as a py-call
;; argument — that crosses unreduced (probed exhaustively).
;;
;; Why eval works here but not in the earlier top-level probes: these are
;; function-equation bodies (= (sbEmitMembers ...) (let* ...)), reduced by the
;; runtime as it evaluates the loop — the same context runMosesLoop's working
;; emitGen runs in. eval forces reduction inside an executing function body;
;; it does NOT in a top-level py-call argument. Context, not syntax.
;;
;; Load AFTER extractors.metta.
;; ============================================================================

!(import! &self "state_builder.py")

;; Canary: prints the run dir at import if PYTHONPATH resolves the module.
!(py-call (state_builder.sb_run_dir))

(= (sbProbe $tag) (py-call (state_builder.probe $tag)))

;; --- direct delegators (scalars already; mirror emitGen/emitNewRun) ---------
(= (sbNewRun)           (py-call (state_builder.new_run)))
(= (sbBeginGen $g)      (py-call (state_builder.begin_gen $g)))
(= (sbGetTotalEvals)    (py-call (state_builder.get_total_evals)))

;; --- input feature spec: emit once per run from the ITable ----------------
;; Boolean problems have $itable in context; strategy problems pass 0 (no-op).
(= (sbSetProblemSpec $itable)
   (py-call (state_builder.set_problem_spec (eval (getArgLabels $itable)))))

;; --- post_selection hook: buffer the selected exemplar's tree -------------
;; Called from inside expandDeme right after $tree is bound. Passes the FULL
;; raw tree (so its program_id matches a member/candidate id). Buffered in
;; Python; flush_gen consumes + validates it against the gen's candidates.
(= (sbSetSelection $tree)
   (py-call (state_builder.set_selection $tree)))

;; --- member loop: eval-bind every extractor result, THEN py-call ------------
;; $expr = short preOrder display; $tree = full raw tree for collision-resistant id.
;; cscore crosses as a flat list via cscoreFields; Python unwraps defensively.
(= (sbEmitMembers $g $os $i $n)
   (if (>= $i $n)
       0
       (let* (
         ($x    (memberByIdx $os $i))
         ($expr (eval (memberExpr   $x)))   ; short display (preOrder)
         ($tree (eval (memberTree   $x)))   ; full raw tree -> collision-resistant id
         ($cs   (eval (cscoreFields (memberCscore $x))))
         ($bs   (eval (memberBScore $x)))
         ($_    (py-call (state_builder.add_member $g $expr $tree $cs $bs)))
       )
       (sbEmitMembers $g $os (+ $i 1) $n))))
(= (sbEmitAllMembers $g $os)
   (let* (($n (eval (metapopSize $os)))) (sbEmitMembers $g $os 0 $n)))

;; --- per-deme emit: iterate optimized-deme tuple, keying knobs + meta by demeId -----
(= (sbEmitDemeKnobs $g $demeId Nil) 0)
(= (sbEmitDemeKnobs $g $demeId (Cons $k $rest))
   (let* (
     ($loc (eval (knobLoc $k))) ($mul (eval (knobMultip $k)))
     ($def (eval (knobDefault $k))) ($tag (eval (knobTag $k)))
     ($_k  (py-call (state_builder.add_knob $g $demeId $loc $mul $def $tag)))
   ) (sbEmitDemeKnobs $g $demeId $rest)))

(= (sbEmitDeme $g $deme)
   (let* (
     ((mkDeme $rep $sInst $demeId) $deme)
     ($inst (eval (List.length (second $sInst))))
     ($_ (sbEmitDemeKnobs $g $demeId (eval (knobsOfRep $rep))))
     ($_ (let $tr (eval (repTree $rep)) (py-call (state_builder.set_deme $g $demeId $tr $inst))))
   ) 0))

;; Named run-parameter buffering (replaces the 12-arg positional sbFlushGen).
;; Values persist in Python until new_run; flush_terminal reuses them without re-set.
(= (sbSetRunParam $name $value)
   (py-call (state_builder.set_run_param $name $value)))

(= (sbSetRunParams $problemType $complexityRatio $maxGen $nEval $maxCandsPerDeme
                   $minPoolSize $complexityTemperature $nToKeep $capCoef $nDeme $optimizer)
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
   ) 0))

;; --- post_deme_close Tier A/B ----------------------------------------------
;; sbBeginMerge MUST be called BEFORE mergeDemes so the in-merge set_merge_count
;; probes land in an open buffer. sbEmitAllMerged only WALKS the post-merge pop.
(= (sbBeginMerge) (py-call (state_builder.begin_merge)))

;; Walk $removedDominated (mkExemplar list) and buffer each as a cull candidate.
;; Called at the probe site in merge-demes.metta, buffer open from sbBeginMerge.
;; cscore fields extracted via named accessors (getScore / getComp / getPenScore)
;; so the three scalars cross as ints/floats rather than as a raw mkCscore atom.
(= (sbEmitCullCands Nil) 0)
(= (sbEmitCullCands (Cons $ex $rest))
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

(= (sbEmitMergedPop $os $i $n)
   (if (>= $i $n) 0
       (let* (($x  (memberByIdx $os $i))
              ($tr (eval (memberTree $x)))
              ($_  (py-call (state_builder.add_merged_member $tr))))
         (sbEmitMergedPop $os (+ $i 1) $n))))
(= (sbEmitAllMerged $os)
   (let* (($n (eval (metapopSize $os))))
     (sbEmitMergedPop $os 0 $n)))

;; --- per-candidate neighborhood size walk ----------------------------------
;; dist-1 neighborhood = Σ(multip−1) over the rep's discrete knob map.
;; When FS is on, createRepresentation may produce multiple reps (one per
;; feature-set candidate); non-determinism means treeNeighborhood returns one
;; $n per rep, and sbEmitCandNbh emits each — Python accumulates a list.
(= (sumNbhMMap NilMMap) 0)
(= (sumNbhMMap (ConsMMap ((mkDiscSpec $m) $knob) $rest))
   (+ (- $m 1) (sumNbhMMap $rest)))

(= (repNeighborhood (mkRep (mkKbMap (mkDscKbMp $dscKbMp) (mkDscMp $dscMp)) $t))
   (sumNbhMMap $dscMp))

;; createRepresentation returns a one-tuple ((mkRep ...)) per feature-set;
;; car-atom peels the outer tuple. With FS on, let binds $reps to each result
;; non-deterministically so repNeighborhood fires once per feature-set.
(= (treeNeighborhood $tree $itable $algo $prune $enforced $scorerType)
   (let $reps (createRepresentation 1 $tree $itable $algo $prune $enforced $scorerType)
     (repNeighborhood (car-atom $reps))))

;; Emit one candidate's neighborhood size(s); non-determinism from
;; treeNeighborhood is resolved by Python appending to a list per program_id.
(= (sbEmitCandNbh $tree $itable $algo $prune $enforced $scorerType)
   (let $n (eval (treeNeighborhood $tree $itable $algo $prune $enforced $scorerType))
     (py-call (state_builder.set_candidate_neighborhood $tree $n))))

(= (sbEmitMemberNbh $os $i $n $itable $algo $prune $enforced $scorerType)
   (if (>= $i $n) 0
     (let* (($x    (memberByIdx $os $i))
            ($tree (eval (memberTree $x)))
            ($_    (sbEmitCandNbh $tree $itable $algo $prune $enforced $scorerType)))
       (sbEmitMemberNbh $os (+ $i 1) $n $itable $algo $prune $enforced $scorerType))))

;; Walk the pre-cull metapop and emit neighborhood size(s) for each member.
;; Called from runMosesLoop (boolean context only) BEFORE sbEmitGeneration.
;; Strategy context passes 0 (no-op) since there is no feature table.
(= (sbEmitAllMemberNbh $os $itable $algo $prune $enforced $scorerType)
   (let* (($n (eval (metapopSize $os))))
     (sbEmitMemberNbh $os 0 $n $itable $algo $prune $enforced $scorerType)))

;; --- one-call convenience: emit a full generation --------------------------
;; sbEmitGeneration takes the WHOLE optimized-deme tuple and iterates via sbEmitDeme.
;; Run parameters are pre-buffered via sbSetRunParams; flush_gen reads them from Python.
(= (sbEmitGeneration $g $metaPop $optimizedDemes)
   (let* (
     ($_g1 (sbBeginGen $g))
     ($_g2 (sbEmitAllMembers $g $metaPop))
     ($_g3 (let $r (map-atom $optimizedDemes $deme (sbEmitDeme $g $deme)) 0))
     ($_g4 (py-call (state_builder.flush_gen $g)))
   ) 0))

;; Terminal snapshot — full ProgramRecords of the FINAL post-merge metapop.
;; Reuses sbBeginGen + sbEmitAllMembers; writes terminal.json (no sentinel).
;; Run parameters are pre-buffered via sbSetRunParams; flush_terminal reads them.
(= (sbEmitTerminal $g $metaPop)
   (let* (
     ($_t1 (sbBeginGen $g))
     ($_t2 (sbEmitAllMembers $g $metaPop))
     ($_t3 (py-call (state_builder.flush_terminal $g)))
   ) 0))

;; Strategy problem spec: no itable exists; the action-space domain is the hardcoded
;; move vocabulary (getAllGameMoves, representation/add-logical-knobs.metta L11)
;; plus the game parameters from the context tuple.
(= (sbSetProblemSpecStrategy $nGames $opponentPolicy $complexityRatio)
   (let* (($moves (eval (getAllGameMoves))))
     (py-call (state_builder.set_problem_spec_strategy $moves $nGames $opponentPolicy $complexityRatio))))

;; Strategy neighborhood: 2-arg createRepresentation (game path) returns the rep
;; tuple from the collapse in representation.metta; nDeme=1 -> one-tuple, same
;; car-atom peel as the boolean path. SSK multiplicity is uniformly 2, so
;; repNeighborhood's Σ(multip−1) = knob count = exact Hamming-1 size.
(= (strategyTreeNeighborhood $tree)
   (let $reps (createRepresentation 1 $tree)
     (repNeighborhood (car-atom $reps))))

(= (sbEmitCandNbhStrategy $tree)
   (let $n (eval (strategyTreeNeighborhood $tree))
     (py-call (state_builder.set_candidate_neighborhood $tree $n))))

(= (sbEmitMemberNbhStrategy $os $i $n)
   (if (>= $i $n) 0
     (let* (($x    (memberByIdx $os $i))
            ($tree (eval (memberTree $x)))
            ($_nb  (sbEmitCandNbhStrategy $tree)))
       (sbEmitMemberNbhStrategy $os (+ $i 1) $n))))

(= (sbEmitAllMemberNbhStrategy $os)
   (let* (($n (eval (metapopSize $os))))
     (sbEmitMemberNbhStrategy $os 0 $n)))

;; Explicit boolean run initializer — call instead of sbNewRun + sbSetProblemSpec.
;; Combines new_run, problem-spec, and run-param buffering in one call.
;; Use for the 4-field context: ($prune $fsAlgo $truthTableBScore $itable)
(= (sbBeginRunBoolean
      $maxGen $nEval $maxCandsPerDeme $minPoolSize $complexityTemperature
      $nToKeep $capCoef $nDeme $optimizer
      $itable)
   (let* (
     ($_0 (sbNewRun))
     ($_1 (sbSetProblemSpec $itable))
     ($_2 (sbSetRunParams
             "boolean" ()
             $maxGen $nEval $maxCandsPerDeme
             $minPoolSize $complexityTemperature
             $nToKeep $capCoef $nDeme $optimizer))
   ) 0))

;; Explicit strategy run initializer — call instead of sbNewRun + sbSetProblemSpecStrategy.
;; Use for the 3-field context: ($nGames $opponentPolicy $complexityRatio)
(= (sbBeginRunStrategy
      $maxGen $nEval $maxCandsPerDeme $minPoolSize $complexityTemperature
      $nToKeep $capCoef $nDeme $optimizer
      $nGames $opponentPolicy $complexityRatio)
   (let* (
     ($_0 (sbNewRun))
     ($_1 (sbSetProblemSpecStrategy $nGames $opponentPolicy $complexityRatio))
     ($_2 (sbSetRunParams
             "strategy" $complexityRatio
             $maxGen $nEval $maxCandsPerDeme
             $minPoolSize $complexityTemperature
             $nToKeep $capCoef $nDeme $optimizer))
   ) 0))
