;; LLMOSES fork of feature-selection/select-top-features.metta.
;; Import this INSTEAD of the base file.
;;
;; Changes vs. base:
;;   * Debug print immediately before jaccardIndex call in rankIterator
;;     (binding name $_jdbg — $_ collapses in PeTTa, distinct name is required).
;;     Remove the $_jdbg line once the FS path is confirmed clean.

;; select top features -- based on value of diversity pressure parameter
;;          $ft-set         -- feature set from feature selection algos
;;          $div-pres       -- diversity pressure parameter -- description in rankFtSet below
;;          $div-interaction-- diversity interaction parameter -- description in rankFtSet below
;;          $sim-scorer     -- ja or mi
;;          $ft-sets        -- pop of feature set oreded by raw score
;;NOTe -- this implementation requires the feature sets to come with their MI score
(= (selectTopFts (mkITable $table $labels) $div-pres $div-interaction $multi-diversity $sim-scorer $ft-sets $nDeme)
    (let* 
       (
         ($fts-size (size-atom $ft-sets))
         ($res-size (min-atom ($fts-size $nDeme)))
         ($seed (py-call (random.randint 0 2147483647))) ;; As per the OpenCog classic this is how we sample a random seed for introducing randomness into lexicographic ordering of feature sets with the same score.
       )
       (if (> $div-pres 0)
                (let $ranked-set (rankFtSet $seed (mkITable $table $labels) $div-pres $div-interaction $multi-diversity $sim-scorer $ft-sets ())
                    (takeN $res-size $ranked-set))
                (let $ft-sets-less-score (map-atom $ft-sets $ft-set (second $ft-set)) (takeN $res-size $ft-sets-less-score))))   ;; strip the scores off the feature sets
)

;;  rankFtSet -- applies diversity pressure to rank feature sets
(= (rankFtSet $seed (mkITable $table $labels) $div-pres $div-interaction $multi-diversity $sim-scorer $ft-sets $acc)
    (let $csc-ft-set 
        (map-atom $ft-sets $ft-set ((mkCscore (first-from-pair $ft-set) (let $set (second-from-pair $ft-set) (size-atom $set)) 0.0 0.0 (first-from-pair $ft-set)) (second-from-pair $ft-set)))
            (rankIterator $seed (mkITable $table $labels) $div-pres $div-interaction $multi-diversity $sim-scorer $csc-ft-set $acc)))

(= (rankIterator $seed (mkITable $table $labels) $div-pres $div-interaction $multi-diversity $sim-scorer $csc-ft-set $acc)
    (if (== $acc ())
        (rankIterator $seed (mkITable $table $labels) $div-pres $div-interaction $multi-diversity $sim-scorer (cdr-atom $csc-ft-set) ((car-atom $csc-ft-set)))
        (if (== $csc-ft-set ())
            (map-atom $acc $a (second $a))
            (let* ( 
                    ($current-ft-set (car-atom $csc-ft-set))
                    ($current-cscore (first-from-pair $current-ft-set))
                    ($current-ft (second-from-pair $current-ft-set))
                    ($last-ft-set (car-atom $acc))
                    ($last-cscore (first-from-pair $last-ft-set))
                    ($last-ft (second $last-ft-set))
                    ($_jdbg (println! (JDBG last= $last-ft current= $current-ft)))   ;; DEBUG — remove after
                    ($sim (if (== $sim-scorer ja)
                                (jaccardIndex $last-ft $current-ft)
                                (mi $current-ft $last-ft $div-interaction (mkITable $table $labels))))
                    ($last-dp (simToPen $sim $div-pres))
                    ($current-unipen-score (getUniPen $current-cscore))
                    ($agg-dp (max-atom ($last-dp $current-unipen-score)))
                    ($updated-uniPen-score (setUniPen $current-cscore $agg-dp))
                    ($updatd-pen-score (updatePenalizedScore $updated-uniPen-score $multi-diversity))
                    ($new-acc (eval (insertPair cScore>= (featureSet< $seed) ($updatd-pen-score $current-ft) $acc)))
                    )
                (rankIterator $seed (mkITable $table $labels) $div-pres $div-interaction $multi-diversity $sim-scorer (cdr-atom $csc-ft-set) $new-acc)))))

;; simToPen similarity to penality
(= (simToPen $sim $div-pres) (* $sim $div-pres))

;; biased randbool
;;          $b -- float [0, 1]
(= (biasedRandBool $b)
    (let $rnd (py-call (random.random)) (> $b $rnd)))

;; sample_enforced_features
(= (sampleEnforcedFts $enforced-fts)
    (collapse (let $enforced-ft (superpose $enforced-fts)
            (let $p (second $enforced-ft) (if (biasedRandBool $p) (first $enforced-ft) (Empty))))))
