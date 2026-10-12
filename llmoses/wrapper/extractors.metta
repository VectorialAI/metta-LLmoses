;; LLMOSES value extractors: MeTTa helpers that pull fields out of MOSES values
;; before wrapper/state-builder.metta passes them to Python.

;; cscoreFields -- (score complexity complexity-penalty uniformity-penalty penalized-score)
(= (cscoreFields $cs)
   ( (getScore $cs) (getComp $cs) (getCompPen $cs) (getUniPen $cs) (getPenScore $cs) ))

;; metapopulation member (exemplar) fields
(= (memberExpr $x)
   (let* (($tree (eval (getExemplarTree $x))))
     (preOrder $tree)))                                  ;; preOrder form, for display only (lossy)
(= (memberTree   $x) (eval (getExemplarTree $x)))        ;; full tree, used for the program_id
(= (memberCscore $x) (eval (getExemplarCscore $x)))      ;; Cscore
(= (memberPen    $x) (eval (getExemplarPenScore $x)))    ;; Number
(= (memberBScore $x) (eval (getExemplarBScore $x)))      ;; (mkBScore $list)
(= (memberFields $x) ( (memberExpr $x) (cscoreFields (memberCscore $x)) ))

;; metapopulation access
(= (metapopSize $os)    (OS.length $os))
(= (memberByIdx $os $i) (OS.getByIdx $i $os))           ;; OS.getByIdx takes the index first

;; representation fields, for one-field (boolean) and two-field (strategy) knob maps
(= (repDscMp (mkRep (mkKbMap (mkDscMp $dscMp)) $tree)) $dscMp)
(= (repTree  (mkRep (mkKbMap (mkDscMp $dscMp)) $tree)) $tree)
(= (repDscMp (mkRep (mkKbMap $dscKbMp (mkDscMp $dscMp)) $tree)) $dscMp)
(= (repTree  (mkRep (mkKbMap $dscKbMp (mkDscMp $dscMp)) $tree)) $tree)

;; knobsOfRep -- lists a representation's knobs by walking the DiscMap directly.
;; One-field knobs are wrapped as (llKnob $i $kb), $i being the knob's position in
;; the DiscMap (and so in the instance); two-field (strategy) knobs carry their own location.
(= (mmapKnobList () $i) ())
(= (mmapKnobList (cons ($kbSpec $kb) $tail) $i)
   (cons (llKnob $i $kb) (mmapKnobList $tail (+ $i 1))))
(= (legacyKnobList ()) ())
(= (legacyKnobList (cons ($kbSpec $kb) $tail))
   (cons $kb (legacyKnobList $tail)))
(= (knobsOfRep (mkRep (mkKbMap (mkDscMp $dscMp)) $tree))
   (mmapKnobList $dscMp 0))
(= (knobsOfRep (mkRep (mkKbMap $dscKbMp (mkDscMp $dscMp)) $tree))
   (legacyKnobList $dscMp))

;; per-knob accessors, for llKnob-wrapped and bare mkLSK/mkSSK knobs
(= (knobLoc     (llKnob $i $kb)) $i)
(= (knobMultip  (llKnob $i $kb)) (getKnobMultip $kb))
(= (knobDefault (llKnob $i $kb)) (getKnobDefault $kb))
(= (knobLoc     (mkLSK $dk)) (getKnobLoc (mkLSK $dk)))
(= (knobLoc     (mkSSK $dk)) (getKnobLoc (mkSSK $dk)))
(= (knobMultip  (mkLSK $dk)) (getKnobMultip (mkLSK $dk)))
(= (knobMultip  (mkSSK $dk)) (getKnobMultip (mkSSK $dk)))
(= (knobDefault (mkLSK $dk)) (getKnobDefault (mkLSK $dk)))
(= (knobDefault (mkSSK $dk)) (getKnobDefault (mkSSK $dk)))

;; knobTag -- LSK or SSK, read from the constructor rather than inferred from multiplicity
(= (knobTag (llKnob $i (mkLSK $dk))) LSK)
(= (knobTag (llKnob $i (mkSSK $dk))) SSK)
(= (knobTag (mkLSK $dk)) LSK)
(= (knobTag (mkSSK $dk)) SSK)
