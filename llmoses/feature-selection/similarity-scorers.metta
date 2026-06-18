;; LLMOSES fork of feature-selection/similarity-scorers.metta
;; Change: jaccardIndex rewritten to avoid union-atom / list_to_set.
;; |A∪B| = |A| + |B| − |A∩B|  →  Jaccard = |A∩B| / (|A| + |B| − |A∩B|)
;; Only intersection-atom and size-atom are used — both PeTTa-proven builtins.

;; mutual information between feature sets
(= (mi $set1 $set2 $div-interaction (mkITable $table $labels))
    (if (< $div-interaction 0)
            (mutualInformationBtwSets $set1 $set2 (mkITable $table $labels))
            (let* (($sss (+ $div-interaction 1))
                    (($ps1 $ps2) (map-atom ($set1 $set2) $set (powerSet $set $sss True)))
                    (($ps1-size $ps2-size) ((size-atom $ps1) (size-atom $ps2)))
                    ($all-comb-mi (map-atom $ps1 $ps-a (map-atom $ps2 $ps-b (mutualInformationBtwSets $ps-a $ps-b (mkITable $table $labels)))))
                    ($inner-sum (map-atom $all-comb-mi $mi (foldl + $mi 0)))
                    ($total-mi (foldl-atom $inner-sum 0 $acc $x (+ $acc $x))))
                    (/ $total-mi (* $ps1-size $ps2-size)))))

;; mutualInformationBtwSets -- calculates MI between feature sets using entropy values
(= (mutualInformationBtwSets $set1 $set2 (mkITable $table $labels))
    (let* (($union (union-atom $set1 $set2))
            ($len (List.length $table))
            (($set1-zip $set2-zip $union-zip) (map-atom ($set1 $set2 $union) $set (zipColumn $set $table)))
            (($zip1-count $zip2-count $union-count) (map-atom ($set1-zip $set2-zip $union-zip) $zip (List.uniqueValuesCount $zip ())))
            (($e1 $e2 $eu) (map-atom ($zip1-count $zip2-count $union-count) $count (entropy $count $len 0))))
            (- (+ $e1 $e2) $eu)))

;; jaccard_index 0 ≤ ji ≤ 1 — intersection-only formula, no union-atom / list_to_set.
;; Verified: (1 2)∩(2 3)=1, |A|+|B|-|A∩B|=2+2-1=3, result=1/3.
;; Identical sets → 1;  disjoint sets → 0/n = 0.
;; (: jaccardIndex (-> Expression Expression Number))
(= (jaccardIndex $s1 $s2)
   (let* (($i (size-atom (intersection-atom $s1 $s2)))
          ($a (size-atom $s1))
          ($b (size-atom $s2)))
     (/ $i (- (+ $a $b) $i))))
