;; ============================================================================
;; llmoses/representation/sample-logical-perms.metta
;;
;; Drop-in replacement for representation/sample-logical-perms.metta — do NOT
;; import the upstream file. Sampling evidence is emitted after merge by
;; state_builder.py, so lazyRandomSelector and the samplers run untouched here.
;; Helpers genPairs / genTriplet / getArgs / getMoveArgs are inlined here so no
;; upstream import is needed.
;; ============================================================================

;; --- inlined helpers from representation/sample-logical-perms ---

(= (genPairs $list)
    (let*
        (
            ($x (superpose $list))
            ($y (superpose $list))
        )
        (if (not (== $x $y))
            ($x $y)
            (empty)
        )
    )
)

(= (genTriplet $list)
    (let*
        (
            ($x (superpose $list))
            ($y (superpose $list))
            ($z (superpose $list))
        )
        (if (and (and (!= $x $y) (!= $y $z)) (!= $x $z))
            ($x $y $z)
            (empty)
        )
    )
)

(= (getArgs $swapedOp $PermPairs $picked $argLabels)
    (let*
        (
            (($a $b) (index-atom $PermPairs (superpose $picked)))
            (($1 $2) ((index-atom $argLabels $a) (index-atom $argLabels $b)))
        )
        (if (< $b $a)
            ($swapedOp $2 $1)
            ($swapedOp (NOT $1) $2)
        )
    )
)

(= (getMoveArgs $op $PermPairs $picked $moveLabels)
    (let*
        (
            (($a $b $c) (index-atom $PermPairs (superpose $picked)))
            (($move1 $move2 $move3) ((index-atom $moveLabels $a) (index-atom $moveLabels $b) (index-atom $moveLabels $c)))
        )
        ($op $move1 $move2 $move3)
    ))

;; --- overlay definitions ---

(= (sampleLogicalPerms $op $arity $argLabels)
    (let*
        ( 
            ($swapedOp (swapAndOr $op))
            ($list (genList (- $arity 1)))
            ($idxPairs (collapse (genPairs $list)))
            ($nPairs $arity))
            (if (<= $nPairs 1)
                (let $arg (car-atom $argLabels) ($arg (NOT $arg)))
                (let* (($upperbound (- (* $arity (- $arity 1)) 1))
                        ($picked (lazyRandomSelector 0 $upperbound $nPairs))
                        ($perms (collapse (getArgs $swapedOp $idxPairs $picked $argLabels))))
                   (concatT $argLabels $perms)))))

(= (sampleStrategyPerms $op $arity $moveLabels)
    (let*
        (
            ($list (genList (- (length $moveLabels) 1)))
            ($idxPairs (collapse (genTriplet $list)))
            ($nPairs $arity)
        )
        (if (<= $nPairs 1)
            ($op (car-atom $moveLabels))
            (let*
                (
                    ($upperbound (- (length $idxPairs) 1))
                    ($picked (lazyRandomSelector 0 $upperbound $nPairs))
                    ($perms (collapse (getMoveArgs $op $idxPairs $picked $moveLabels)))
                )
                   $perms
            )
        )
))
