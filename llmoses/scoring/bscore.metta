;; ============================================================================
;; llmoses/scoring/bscore.metta
;;
;; Overlay for scoring/bscore.metta — import INSTEAD OF the upstream module.
;; Replaces scoreTree's cache key from bare $tree to ($ctx $tree ...) where
;; $ctx is the full mkITable, preventing cross-table cache poisoning when the
;; same tree shape is scored against different truth tables.
;; ============================================================================

!(import! &self scoring/bscore)

(= (scoreTree (mkITable $table $labels) $tree $cacheSpace)
   (if (== $tree (mkTree (mkNode AND) Nil))
       (worstPossibleScore (createTruthTableBScore $compCoeff (mkITable $table $labels)))
       (let $ctx (mkITable $table $labels)
         (chain (collapse (match $cacheSpace ($ctx $tree $bscore) $bscore)) $val
           (if (== $val ())
               (let* (
                   ($expTree (preOrder $tree))
                   ($scoreList (eval (List.map (compose evaluate ((curry replaceVarsWithTruth) ($labels $expTree))) $table)))
                   ($length (List.length $labels))
                   ($outputs (eval (List.flatten (List.map (eval (List.drop (- $length 1))) $table))))
                   ($bScore (List.zipWith compareAndScore $scoreList $outputs))
                   ($result (mkBScore $bScore))
                   ($_ (add-atom $cacheSpace ($ctx $tree $result)))
               )
               $result)
               (car-atom $val))))))
