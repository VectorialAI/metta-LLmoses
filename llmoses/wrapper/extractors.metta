;; LLMOSES value extractors.
;; Pure MeTTa helpers used by the state-builder wrapper before values cross
;; into Python. knobsOfRep walks the DscMp structure directly instead of relying
;; on MultiMap.values.

;; --- CSCORE: five raw fields via native getters; one ordered bundle ---------
(= (cscoreFields $cs)
   ( (getScore $cs) (getComp $cs) (getCompPen $cs) (getUniPen $cs) (getPenScore $cs) ))

;; --- MEMBER (exemplar) via native getters -----------------------------------
(= (memberExpr $x)
   (let* (($tree (eval (getExemplarTree $x))))
     (preOrder $tree)))                                  ;; short display (preOrder; lossy)
(= (memberTree   $x) (eval (getExemplarTree $x)))        ;; full raw tree for stable program_id
(= (memberCscore $x) (eval (getExemplarCscore $x)))      ;; Cscore
(= (memberPen    $x) (eval (getExemplarPenScore $x)))    ;; Number
(= (memberBScore $x) (eval (getExemplarBScore $x)))      ;; (mkBScore $list); Python unwraps
(= (memberFields $x) ( (memberExpr $x) (cscoreFields (memberCscore $x)) ))

;; --- METAPOP traversal: confirmed native primitives -------------------------
(= (metapopSize $os)    (OS.length $os))
(= (memberByIdx $os $i) (OS.getByIdx $i $os))           ;; native arg order: idx first

;; --- REPRESENTATION field pulls (upstream mkKbMap now owns one DiscMap) ------
(= (repDscMp (mkRep (mkKbMap (mkDscMp $dscMp)) $tree)) $dscMp)
(= (repTree  (mkRep (mkKbMap (mkDscMp $dscMp)) $tree)) $tree)
(= (repDscMp (mkRep (mkKbMap $dscKbMp (mkDscMp $dscMp)) $tree)) $dscMp)
(= (repTree  (mkRep (mkKbMap $dscKbMp (mkDscMp $dscMp)) $tree)) $tree)

;; --- KNOBS: upstream embeds the location/index in mkKnob tree wrappers. -------
;; The DiscMap preserves that instance order, so enumerate it and carry the
;; index beside each logical/strategy knob for state emission.
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

;; --- Per-knob native accessors (thin delegating names) ----------------------
(= (knobLoc     (llKnob $i $kb)) $i)
(= (knobMultip  (llKnob $i $kb)) (getKnobMultip $kb))
(= (knobDefault (llKnob $i $kb)) (getKnobDefault $kb))
(= (knobLoc     (mkLSK $dk)) (getKnobLoc (mkLSK $dk)))
(= (knobLoc     (mkSSK $dk)) (getKnobLoc (mkSSK $dk)))
(= (knobMultip  (mkLSK $dk)) (getKnobMultip (mkLSK $dk)))
(= (knobMultip  (mkSSK $dk)) (getKnobMultip (mkSSK $dk)))
(= (knobDefault (mkLSK $dk)) (getKnobDefault (mkLSK $dk)))
(= (knobDefault (mkSSK $dk)) (getKnobDefault (mkSSK $dk)))

;; --- DEME fields: NOT extracted here; runMosesLoop already binds $rep/$sInst/$demeId.

;; Constructor tag: discriminates knob family without relying on multiplicity.
(= (knobTag (llKnob $i (mkLSK $dk))) LSK)
(= (knobTag (llKnob $i (mkSSK $dk))) SSK)
(= (knobTag (mkLSK $dk)) LSK)
(= (knobTag (mkSSK $dk)) SSK)
