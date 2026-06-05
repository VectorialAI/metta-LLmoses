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
     ($loc (eval (knobLoc $k))) ($mul (eval (knobMultip $k))) ($def (eval (knobDefault $k)))
     ($_  (py-call (state_builder.add_knob $g $demeId $loc $mul $def)))
   ) (sbEmitDemeKnobs $g $demeId $rest)))

(= (sbEmitDeme $g $deme)
   (let* (
     ((mkDeme $rep $sInst $demeId) $deme)
     ($inst (eval (List.length (second $sInst))))
     ($_ (sbEmitDemeKnobs $g $demeId (eval (knobsOfRep $rep))))
     ($_ (let $tr (eval (repTree $rep)) (py-call (state_builder.set_deme $g $demeId $tr $inst))))
   ) 0))

;; flush_gen takes 12 positional args IN THIS ORDER (matches state_builder.py):
;;   gen problem_type complexity_ratio max_gen n_eval max_cands_per_deme
;;   min_pool_size complexity_temperature n_to_keep cap_coef n_deme optimizer
(= (sbFlushGen $g $problemType $complexityRatio $maxGen $nEval $maxCandsPerDeme
               $minPoolSize $complexityTemperature $nToKeep $capCoef $nDeme $optimizer)
   (py-call (state_builder.flush_gen $g $problemType $complexityRatio $maxGen $nEval
              $maxCandsPerDeme $minPoolSize $complexityTemperature $nToKeep $capCoef
              $nDeme $optimizer)))

;; --- post_deme_close Tier A/B ----------------------------------------------
;; sbBeginMerge MUST be called BEFORE mergeDemes so the in-merge set_merge_count
;; probes land in an open buffer. sbEmitAllMerged only WALKS the post-merge pop.
(= (sbBeginMerge) (py-call (state_builder.begin_merge)))

(= (sbEmitMergedPop $os $i $n)
   (if (>= $i $n) 0
       (let* (($x  (memberByIdx $os $i))
              ($tr (eval (memberTree $x)))
              ($_  (py-call (state_builder.add_merged_member $tr))))
         (sbEmitMergedPop $os (+ $i 1) $n))))
(= (sbEmitAllMerged $os)
   (let* (($n (eval (metapopSize $os))))
     (sbEmitMergedPop $os 0 $n)))

;; --- one-call convenience: emit a full generation --------------------------
;; sbEmitGeneration takes the WHOLE optimized-deme tuple and iterates via sbEmitDeme.
(= (sbEmitGeneration $g $metaPop $optimizedDemes
                     $problemType $complexityRatio $maxGen $nEval $maxCandsPerDeme
                     $minPoolSize $complexityTemperature $nToKeep $capCoef $nDeme $optimizer)
   (let* (
     ($_ (sbBeginGen $g))
     ($_ (sbEmitAllMembers $g $metaPop))
     ($_ (let $r (map-atom $optimizedDemes $deme (sbEmitDeme $g $deme)) 0))
     ($_ (sbFlushGen $g $problemType $complexityRatio $maxGen $nEval $maxCandsPerDeme
                     $minPoolSize $complexityTemperature $nToKeep $capCoef $nDeme $optimizer))
   )
   0))

;; Terminal snapshot — full ProgramRecords of the FINAL post-merge metapop.
;; Reuses sbBeginGen + sbEmitAllMembers; writes terminal.json (no sentinel).
(= (sbEmitTerminal $g $metaPop $problemType $complexityRatio $maxGen $nEval $maxCandsPerDeme
                   $minPoolSize $complexityTemperature $nToKeep $capCoef $nDeme $optimizer)
   (let* (
     ($_ (sbBeginGen $g))
     ($_ (sbEmitAllMembers $g $metaPop))
     ($_ (py-call (state_builder.flush_terminal $g $problemType $complexityRatio $maxGen $nEval
                    $maxCandsPerDeme $minPoolSize $complexityTemperature $nToKeep $capCoef
                    $nDeme $optimizer)))
   ) 0))
