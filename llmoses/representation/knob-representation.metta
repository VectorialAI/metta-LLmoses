;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; LLMOSES – knob-representation overlay (regression / mkCSK)                  ;;
;;                                                                           ;;
;; Import INSTEAD OF representation/knob-representation. Pulls in the base   ;;
;; definitions, then adds mkCSK accessor equations for contin trit knobs.    ;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

!(import! &self representation/knob-representation)

;; Contin trit knob (regression): mkCSK wraps a DiscKnob plus a
;; (mkContinSpec mean step_size expansion depth group) metadata record.
(= (getDiscKnob (mkCSK $DiscKnob $continSpec)) $DiscKnob)
(= (getKnobMultip (mkCSK $discKnob $continSpec)) (getKnobMultip $discKnob))
(= (getKnobLoc (mkCSK $discKnob $continSpec)) (getKnobLoc $discKnob))
