;; LLMOSES overlay of scoring/bscore.metta. Import this instead of the upstream
;; file; it imports upstream itself and adds the scoreTree clause below.
;; scoreTree caches on (ITable, tree) rather than tree alone, so a tree scored
;; against two different truth tables doesn't reuse the wrong result.

!(import! &self scoring/bscore)

(= (scoreTree (mkITable $table $labels) $tree $cacheSpace)
   (if (== $tree (mkTree (mkNode AND) ()))
       (worstPossibleScore (createTruthTableBScore $compCoeff (mkITable $table $labels)))
       (let $ctx (mkITable $table $labels)
         (chain (collapse (match $cacheSpace
                 ($ctx $tree $bscore)
                 $bscore))
             $val
           (if (== $val ())
               (let* (
                   ($expTree (preOrder $tree))
                   ($scoreList (map-atom $table $ts (scoreTreeHelper $labels $expTree $ts)))
                   ($length (List.length $labels))
                   ($outputs (List.flatten (List.map (List.drop (- $length 1)) $table)))
                   ($bScore (List.zipWith compareAndScore $scoreList $outputs))
                   ($result (mkBScore $bScore))
                   ($_ (add-atom $cacheSpace ($ctx $tree $result)))
               )
               $result)
               (car-atom $val)
           )))))
