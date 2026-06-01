;; ============================================================================
;; llmoses/wrapper/extractors.metta  (v3 — verified against re-uploaded main)
;;
;; knobsOfRep walks the DscMp by STRUCTURE (mirrors crtDiscKnobMap in
;; representation.metta) instead of calling MultiMap.values, which is not present
;; in the provided source. Everything else CALLS native accessors verified in the
;; re-uploaded files. Pure (no py-call); each stays assert-testable.
;; ============================================================================

;; --- CSCORE: five raw fields via native getters; one ordered bundle ---------
(= (cscoreFields $cs)
   ( (getScore $cs) (getComp $cs) (getCompPen $cs) (getUniPen $cs) (getPenScore $cs) ))

;; --- MEMBER (exemplar) via native getters -----------------------------------
(= (memberExpr   $x) (preOrder (getExemplarTree $x)))   ; -> expression
(= (memberCscore $x) (getExemplarCscore $x))            ; -> Cscore
(= (memberPen    $x) (getExemplarPenScore $x))          ; -> Number (native)
(= (memberBScore $x) (getExemplarBScore $x))            ; -> (mkBScore $list); Python unwraps
(= (memberFields $x) ( (memberExpr $x) (cscoreFields (memberCscore $x)) ))

;; --- METAPOP traversal: confirmed native primitives -------------------------
(= (metapopSize $os)    (OS.length $os))
(= (memberByIdx $os $i) (OS.getByIdx $i $os))           ; native arg order: idx FIRST

;; --- REPRESENTATION field pulls (shape verified in representation.metta) -----
(= (repDscMp (mkRep (mkKbMap (mkDscKbMp $dscKbMp) (mkDscMp $dscMp)) $tree)) $dscMp)
(= (repTree  (mkRep (mkKbMap (mkDscKbMp $dscKbMp) (mkDscMp $dscMp)) $tree)) $tree)

;; --- KNOBS: walk the DscMp MultiMap by STRUCTURE (mirrors crtDiscKnobMap) ----
;; Strips each (knobSpec knob) pair to the knob, recursing the ConsMMap spine.
(= (mmapKnobList NilMMap) Nil)
(= (mmapKnobList (ConsMMap ($kbSpec $kb) $tail)) (Cons $kb (mmapKnobList $tail)))
(= (knobsOfRep $rep) (mmapKnobList (repDscMp $rep)))

;; --- Per-knob native accessors (thin delegating names) ----------------------
(= (knobLoc     $kb) (getKnobLoc     $kb))   ; native -> NodeId
(= (knobMultip  $kb) (getKnobMultip  $kb))   ; native -> raw multiplicity field (mkMultip n)
(= (knobDefault $kb) (getKnobDefault $kb))   ; native (expand-deme) -> Number

;; --- DEME fields: NOT extracted here; runMosesLoop already binds $rep/$sInst/$demeId.
