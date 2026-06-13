;; ============================================================================
;; llmoses/representation/build-contin.metta
;;
;; Contin (regression) representation building: the linear-combination
;; template (offset + Σ coeffᵢ·featureᵢ — no transcendentals/division in v0),
;; mkCSK trit knobs, and the trit-walk decoder.
;;
;; Decoder semantics verified against asmoses field_set.cc (get_contin /
;; contin_stepper) — NOT the Appendix-B prose, which gets the reversal
;; arithmetic wrong:
;;   - state fold over (value, step, all_left, all_right), starting at
;;     (mean, step_size, true, true)
;;   - same-direction move: value ±= step; step *= expansion
;;   - FIRST reversal: step /= (expansion * 2) BEFORE the move, then the
;;     move, then step /= 2 (binary-search tail)
;;   - subsequent moves after any reversal: move, then step /= 2
;;   - Stop truncates the walk (all-Stop decodes to the mean); trits after a
;;     Stop are ignored
;;   - trit encoding: Stop = 0, Left = 1, Right = 2
;; asmoses defaults (representation.cc): step_size = 1.0, expansion = 2.0,
;; depth = 5. We default depth to 4 to keep test neighborhoods tractable.
;;
;; Knob shape: one coefficient = $depth mkCSK trit knobs of multiplicity 3,
;; each wrapping the standard mkDiscKnob plus a
;; (mkContinSpec $mean $stepSize $expansion $depth $group) metadata record.
;; Group 0 is the offset; group g >= 1 is the coefficient of input feature g.
;; Knobs of a group are CONSECUTIVE in the DscMp spine, in group order — the
;; decoder chunks the instance by that invariant.
;; ============================================================================

;; --- defaults ---------------------------------------------------------------
(= (continDepth) 4)
(= (continStepSize) 1.0)
(= (continExpansion) 2.0)

;; --- trit-walk decoder -------------------------------------------------------
;; Fold one trit list into a value. $allL / $allR track "every move so far was
;; left/right" (both start True; a Stop never flips them since it truncates).
;; (: continWalk (-> (List Number) Number Number Number Bool Bool Number))
(= (continWalk Nil $value $step $expansion $allL $allR) $value)
(= (continWalk (Cons $t $ts) $value $step $expansion $allL $allR)
   (if (== $t 0)
       $value                                                   ;; Stop truncates
       (if (== $t 1)                                            ;; Left
           (if $allL
               (continWalk $ts (- $value $step) (* $step $expansion) $expansion True False)
               (if $allR
                   (let $s (/ $step (* $expansion 2))           ;; first reversal
                     (continWalk $ts (- $value $s) (/ $s 2) $expansion False False))
                   (continWalk $ts (- $value $step) (/ $step 2) $expansion False False)))
           ;; Right ($t == 2)
           (if $allR
               (continWalk $ts (+ $value $step) (* $step $expansion) $expansion False True)
               (if $allL
                   (let $s (/ $step (* $expansion 2))           ;; first reversal
                     (continWalk $ts (+ $value $s) (/ $s 2) $expansion False False))
                   (continWalk $ts (+ $value $step) (/ $step 2) $expansion False False))))))

;; Decode one trit group against its contin spec parameters.
;; (: decodeContinTrits (-> Number Number Number (List Number) Number))
(= (decodeContinTrits $mean $stepSize $expansion $trits)
   (continWalk $trits $mean $stepSize $expansion True True))

;; Decode a whole instance against the knob list (MultiMap.values order).
;; Each group's knobs are consecutive and carry the same spec, so we read the
;; spec off the group head, chunk $depth trits, and skip the sibling knobs.
;; Mismatch arms fail loudly — a broken trit-count invariant must not decode
;; to a silent partial/wrong coefficient vector.
;; (: decodeContinInstance (-> (List CSK) (List Number) (List Number)))
(= (decodeContinInstance Nil Nil) Nil)
(= (decodeContinInstance Nil $trits)
   (if (== $trits Nil) Nil (Error $trits "contin decode: knobs exhausted before trits")))
(= (decodeContinInstance $knobs Nil)
   (if (== $knobs Nil) Nil (Error $knobs "contin decode: trits exhausted before knobs")))
(= (decodeContinInstance (Cons (mkCSK $dk (mkContinSpec $mean $stepSize $expansion $depth $group)) $restKnobs) $trits)
   (let*
     (
       ($groupTrits (List.takeN $depth $trits))
       ($restTrits (List.drop $depth $trits))
       ($siblingKnobs (List.drop (- $depth 1) $restKnobs))
       ($value (decodeContinTrits $mean $stepSize $expansion $groupTrits))
     )
     (Cons $value (decodeContinInstance $siblingKnobs $restTrits))))

;; --- linear template ---------------------------------------------------------
;; (+ c0 (* c1 X1) ... (* cn Xn)) as an mkTree. Constants are numeric node
;; values; one (* c X) term per input label.
;; (: linearTermTrees (-> (List Number) (List Symbol) (List (Tree Number))))
(= (linearTermTrees Nil Nil) Nil)
(= (linearTermTrees (Cons $c $cs) (Cons $l $ls))
   (Cons (mkTree (mkNode *) (Cons (mkTree (mkNode $c) Nil) (Cons (mkTree (mkNode $l) Nil) Nil)))
         (linearTermTrees $cs $ls)))

;; (: buildLinearTree (-> (List Number) (List Symbol) (Tree Number)))
(= (buildLinearTree (Cons $c0 $coeffs) $labels)
   (mkTree (mkNode +) (Cons (mkTree (mkNode $c0) Nil) (linearTermTrees $coeffs $labels))))

;; --- exemplar coefficient extraction ------------------------------------------
;; Seed knob means from the exemplar's constants when it has the linear shape
;; (the asmoses analog: contin_knob takes its mean from the target subtree).
;; Anything that doesn't match — including the bare (+) empty seed — yields 0s.
;; NOTE: dispatch deliberately goes through case (first matching arm wins)
;; rather than overlapping equations: an equation pair "specific pattern" +
;; "catch-all" BOTH succeed on a matching term, making the whole
;; representation build nondeterministic (observed: 3 results per
;; continRepresentation call, two with zeroed means).
(= (continTermCoeff $label Nil) 0)
(= (continTermCoeff $label (Cons $term $rest))
   (case $term
     (((mkTree (mkNode *) (Cons (mkTree (mkNode $c) Nil) (Cons (mkTree (mkNode $l) Nil) Nil)))
       (if (== $l $label) $c (continTermCoeff $label $rest)))
      ($_other (continTermCoeff $label $rest)))))

(= (continOffsetOf $tree)
   (case $tree
     (((mkTree (mkNode +) (Cons (mkTree (mkNode $c) Nil) $rest))
       (if (== (get-metatype $c) Grounded) $c 0))
      ($_other 0))))

;; Canonical contin seed: (+) with no children (cold start), or (+ c0 (* c1 X1) ...)
;; where c0 is a numeric constant and every remaining child is (* c Xi) with Xi
;; in the input-label list. Non-canonical shapes like (+ (* 2 X) 1) are rejected
;; rather than silently zeroing the offset.
(= (continIsMulTerm $label $term)
   (case $term
     (((mkTree (mkNode *) (Cons (mkTree (mkNode $c) Nil) (Cons (mkTree (mkNode $l) Nil) Nil)))
       (== $l $label))
      ($_ False)))

(= (continTermsCoverLabels Nil $terms) True)
(= (continTermsCoverLabels (Cons $l $ls) $terms)
   (and (continIsMulTerm $l $terms) (continTermsCoverLabels $ls $terms)))

;; (: continCoeffsFor (-> (List Symbol) (List (Tree Number)) (List Number)))
(= (continCoeffsFor Nil $terms) Nil)
(= (continCoeffsFor (Cons $l $ls) $terms)
   (Cons (continTermCoeff $l $terms) (continCoeffsFor $ls $terms)))

(= (continHasCanonicalShape (mkTree (mkNode +) Nil) $inputLabels) True))
(= (continHasCanonicalShape $exemplar $inputLabels)
   (case $exemplar
     (((mkTree (mkNode +) (Cons (mkTree (mkNode $c0) Nil) $rest))
       (and (== (get-metatype $c0) Grounded)
            (continTermsCoverLabels $inputLabels $rest)))
      ($_ False)))

(= (continMeansFor $exemplar $inputLabels)
   (if (continHasCanonicalShape $exemplar $inputLabels)
       (let*
         (
           ($offset (continOffsetOf $exemplar))
           ($terms (case $exemplar
                     (((mkTree (mkNode +) $children) $children)
                      ($_other Nil))))
           ($coeffs (continCoeffsFor $inputLabels $terms))
         )
         (Cons $offset $coeffs))
       (Error $exemplar "Non-canonical contin seed: expected (+ c0 (* c1 X1) ...)")))

;; --- knob construction ---------------------------------------------------------
;; $depth trit knobs for one coefficient group. Knob locs (mkNodeId ($g $t))
;; are unique and nodeId<-comparable, so crtDiscKnobMap builds the index map
;; unchanged. Default/initial settings are 0 (Stop) — the all-Stop instance
;; decodes to the means, i.e. the (possibly re-seeded) exemplar itself.
(= (continKnobsForGroup $group $mean $tritIdx $depth)
   (if (== $tritIdx $depth)
       Nil
       (Cons (mkCSK (mkDiscKnob (mkKnob (mkNodeId ($group $tritIdx))) (mkMultip 3) (mkDiscSpec 0) (mkDiscSpec 0) Nil)
                    (mkContinSpec $mean (continStepSize) (continExpansion) $depth $group))
             (continKnobsForGroup $group $mean (+ $tritIdx 1) $depth))))

;; One group of knobs per mean, groups numbered from 0 in means order.
(= (continKnobsFromMeans $group Nil $depth) Nil)
(= (continKnobsFromMeans $group (Cons $mean $means) $depth)
   (List.concat (continKnobsForGroup $group $mean 0 $depth)
                (continKnobsFromMeans (+ $group 1) $means $depth)))

;; Build the DscMp spine directly (key (mkDiscSpec 3) mirrors the LSK
;; multiplicity-keyed inserts; order is preserved verbatim).
(= (knobsToDscMp Nil) NilMMap)
(= (knobsToDscMp (Cons $k $ks)) (ConsMMap ((mkDiscSpec 3) $k) (knobsToDscMp $ks)))

;; --- representation / deme construction -----------------------------------------
;; Contin representation: linear template with knob means as constants, plus
;; the mkCSK trit knobs. Same mkRep shape as boolean/strategy so getDisk,
;; expandDemeHelper, and the state-builder extractors destructure it as-is.
;; (: continRepresentation (-> (Tree Number) (ITable Number) Representation))
(= (continRepresentation $exemplar (mkITable $rows $labels))
   (let*
     (
       ($nInputs (- (List.length $labels) 1))
       ($inputLabels (List.takeN $nInputs $labels))
       ($means (continMeansFor $exemplar $inputLabels))
       ($depth (continDepth))
       ($knobList (continKnobsFromMeans 0 $means $depth))
       ($dscMp (knobsToDscMp $knobList))
       ($dscKbMp (crtDiscKnobMap (mkDscMp $dscMp) (mkDscKbMp NilMap) 0))
       ($template (buildLinearTree $means $inputLabels))
     )
     (mkRep (mkKbMap $dscKbMp (mkDscMp $dscMp)) $template)))

;; Deme construction loop (contin analog of loopCreateDeme; demes share the
;; exemplar but each gets its own freshly built representation).
(= (continLoopCreateDeme Nil $exemplar $itable $acc) $acc)
(= (continLoopCreateDeme (Cons $demeId $demeIds) $exemplar $itable $acc)
   (let*
     (
       ($rep (continRepresentation $exemplar $itable))
       ($deme (mkDeme $rep (mkSInstSet Nil) $demeId))
       ($newAcc (union-atom $acc ($deme)))
     )
     (continLoopCreateDeme $demeIds $exemplar $itable $newAcc)))

;; (: createContinDeme (-> Number (List DemeId) (Tree Number) (ITable Number) Expression))
(= (createContinDeme $nDeme $demeIds $exemplar $itable)
   (continLoopCreateDeme $demeIds $exemplar $itable ()))

;; --- candidate materialization ----------------------------------------------------
;; Decode the instance into coefficients and rebuild the linear tree against
;; the template's labels. Replaces the NodeId-walking getCandidate for contin
;; reps (multiple trit knobs map to ONE template constant, so the 1:1
;; knob-per-node walk cannot apply).
;; case dispatch for the same nondeterminism reason as continTermCoeff above.
(= (templateLabelsFromChildren Nil) Nil)
(= (templateLabelsFromChildren (Cons $term $rest))
   (case $term
     (((mkTree (mkNode *) (Cons $c (Cons (mkTree (mkNode $l) Nil) Nil)))
       (Cons $l (templateLabelsFromChildren $rest)))
      ($_other (templateLabelsFromChildren $rest)))))

(= (templateLabels (mkTree (mkNode +) $children)) (templateLabelsFromChildren $children))

;; Deme-index slot from mkDemeId (1.0), (1.1), ... used to diversify the
;; all-Stop baseline when nDeme > 1 — identical contin reps otherwise run
;; deterministic hill climbing from the same center and produce duplicate trees.
(= (continDemeSlot (mkDemeId ($gen $slot))) $slot)
(= (continDemeSlot (mkDemeId $single)) 0)

;; All-Stop baseline, then a single Left trit at (slot mod nKnobs) when slot > 0.
(= (continInitInstance (mkRep (mkKbMap $kbm (mkDscMp $dscMp)) $template) $demeId)
   (let* (
     ($base (createInitialInstance $dscMp))
     ($n (List.length $base))
     ($slot (continDemeSlot $demeId))
     ($idx (if (== $n 0) 0 (% $slot $n)))
   )
   (if (== $slot 0)
       $base
       (List.replaceAt $base $idx 1))))

;; Detect contin (CSK) knobs in a DscMp spine — used to route init instances
;; without overlapping the boolean catch-all pattern.
(= (repHasContinKnob NilMMap) False)
(= (repHasContinKnob (ConsMMap ($spec $k) $rest))
   (if (== (get-metatype $k) mkCSK)
       True
       (repHasContinKnob $rest)))
(= (repHasContinKnob $_other) False)

;; Route contin reps to continInitInstance; boolean/strategy keep createInitialInstance.
(= (initialInstanceForRep (mkRep (mkKbMap $kbm (mkDscMp $dscMp)) $tree) $demeId $dscMp)
   (if (repHasContinKnob $dscMp)
       (continInitInstance (mkRep (mkKbMap $kbm (mkDscMp $dscMp)) $tree) $demeId)
       (createInitialInstance $dscMp)))

;; (: getContinCandidate (-> Representation Instance (Tree Number)))
(= (getContinCandidate (mkRep (mkKbMap $kbm (mkDscMp $dscMp)) $template) (mkInst $trits))
   (let*
     (
       ($knobs (MultiMap.values $dscMp))
       ($nKnobs (List.length $knobs))
       ($nTrits (List.length $trits))
     )
     (if (not (== $nKnobs $nTrits))
         (Error ($nKnobs $nTrits) "contin instance trit count mismatch")
         (let*
           (
             ($coeffs (decodeContinInstance $knobs $trits))
             ($labels (templateLabels $template))
           )
           (buildLinearTree $coeffs $labels))))))
