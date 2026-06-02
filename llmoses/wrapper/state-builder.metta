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
(= (sbNewRun)        (py-call (state_builder.new_run)))
(= (sbBeginGen $g)   (py-call (state_builder.begin_gen $g)))

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

;; --- knob loop: eval-bind each knob field, THEN py-call ---------------------
(= (sbEmitKnobs $g Nil) 0)
(= (sbEmitKnobs $g (Cons $k $rest))
   (let* (
     ($loc  (eval (knobLoc     $k)))
     ($mul  (eval (knobMultip  $k)))
     ($def  (eval (knobDefault $k)))
     ($_    (py-call (state_builder.add_knob $g $loc $mul $def)))
   )
   (sbEmitKnobs $g $rest)))
(= (sbEmitAllKnobs $g $rep)
   (let* (($ks (eval (knobsOfRep $rep)))) (sbEmitKnobs $g $ks)))

;; --- deme meta + flush: eval-bind the tree, THEN py-call -------------------
(= (sbSetDeme $g $demeId $rep $instances)
   (let* (
     ($tree (eval (repTree $rep)))
     ($_    (py-call (state_builder.set_deme_meta $g $demeId $tree $instances)))
   )
   0))

;; flush_gen takes 12 positional args IN THIS ORDER (matches state_builder.py):
;;   gen problem_type complexity_ratio max_gen n_eval max_cands_per_deme
;;   min_pool_size complexity_temperature n_to_keep cap_coef n_deme optimizer
(= (sbFlushGen $g $problemType $complexityRatio $maxGen $nEval $maxCandsPerDeme
               $minPoolSize $complexityTemperature $nToKeep $capCoef $nDeme $optimizer)
   (py-call (state_builder.flush_gen $g $problemType $complexityRatio $maxGen $nEval
              $maxCandsPerDeme $minPoolSize $complexityTemperature $nToKeep $capCoef
              $nDeme $optimizer)))

;; --- one-call convenience: emit a full generation --------------------------
;; Order: begin -> members -> knobs -> deme meta -> flush. Caller supplies the
;; metapop, the deme's $rep/$demeId/$instances, and the run-parameter scalars.
(= (sbEmitGeneration $g $metaPop $demeId $rep $instances
                     $problemType $complexityRatio $maxGen $nEval $maxCandsPerDeme
                     $minPoolSize $complexityTemperature $nToKeep $capCoef $nDeme $optimizer)
   (let* (
     ($_ (sbBeginGen $g))
     ($_ (sbEmitAllMembers $g $metaPop))
     ($_ (sbEmitAllKnobs $g $rep))
     ($_ (sbSetDeme $g $demeId $rep $instances))
     ($_ (sbFlushGen $g $problemType $complexityRatio $maxGen $nEval $maxCandsPerDeme
                     $minPoolSize $complexityTemperature $nToKeep $capCoef $nDeme $optimizer))
   )
   0))
