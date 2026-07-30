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

;; --- REPRESENTATION field pulls (shape verified in representation.metta) -----
(= (repDscMp (mkRep (mkKbMap (mkDscKbMp $dscKbMp) (mkDscMp $dscMp)) $tree)) $dscMp)
(= (repTree  (mkRep (mkKbMap (mkDscKbMp $dscKbMp) (mkDscMp $dscMp)) $tree)) $tree)

;; --- KNOBS: walk the DscMp MultiMap by STRUCTURE (mirrors crtDiscKnobMap) ----
;; Strips each (knobSpec knob) pair to the knob, recursing the ConsMMap spine.
(= (mmapKnobList NilMMap) Nil)
(= (mmapKnobList (ConsMMap ($kbSpec $kb) $tail)) (Cons $kb (mmapKnobList $tail)))
(= (knobsOfRep $rep) (mmapKnobList (repDscMp $rep)))

;; --- Per-knob native accessors (thin delegating names) ----------------------
(= (knobLoc     $kb) (getKnobLoc     $kb))   ;; native NodeId
(= (knobMultip  $kb) (getKnobMultip  $kb))   ;; native raw multiplicity field (mkMultip n)
(= (knobDefault $kb) (getKnobDefault $kb))   ;; native Number

;; Relocated from the expand-deme fork so the wrapper files can load before
;; expand-deme. expand-deme's own createInitialInstance use resolves fine,
;; since extractors now loads first.
(= (getKnobDefault (mkLSK (mkDiscKnob $knob $multip $curr (mkDiscSpec $def) $dis))) $def)
(= (getKnobDefault (mkSSK (mkDiscKnob $knob $multip $curr (mkDiscSpec $def) $dis))) $def)

;; --- DEME fields: NOT extracted here; runMosesLoop already binds $rep/$sInst/$demeId.

;; Constructor tag: discriminates knob family without relying on multiplicity.
(= (knobTag (mkLSK $dk)) LSK)
(= (knobTag (mkSSK $dk)) SSK)
