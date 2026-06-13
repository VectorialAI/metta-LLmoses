;; ============================================================================
;; llmoses/scoring/numeric-eval.metta
;;
;; Numeric tree evaluator for the regression problem type. Evaluates preOrder
;; expressions of contin trees over {+, *, numeric constants, input variables}
;; against a single numeric row.
;;
;; Structural template: evaluate/rowFitness in scoring/fitness.metta, except
;; variable substitution is done by lookup against a (label value) pair list
;; rather than a space, and arithmetic replaces boolean junctors.
;;
;; v0 scope: + and * only (no transcendentals, no division).
;; ============================================================================

;; Look a variable up in a List of ($label $value) pairs (built by List.zip).
;; (: lookupNumeric (-> Symbol (List ($l $v)) Number))
(= (lookupNumeric $sym Nil) (Error $sym "Unknown variable in numeric expression"))
(= (lookupNumeric $sym (Cons ($l $v) $rest))
   (if (== $sym $l) $v (lookupNumeric $sym $rest)))

;; Sum the evaluations of an argument tuple.
;; (: sumEvalNumeric (-> Expression (List ($l $v)) Number))
(= (sumEvalNumeric () $pairs) 0)
(= (sumEvalNumeric $args $pairs)
   (let ($h $t) (decons-atom $args)
     (+ (evalNumeric $h $pairs) (sumEvalNumeric $t $pairs))))

;; Multiply the evaluations of an argument tuple.
;; (: prodEvalNumeric (-> Expression (List ($l $v)) Number))
(= (prodEvalNumeric () $pairs) 1)
(= (prodEvalNumeric $args $pairs)
   (let ($h $t) (decons-atom $args)
     (* (evalNumeric $h $pairs) (prodEvalNumeric $t $pairs))))

;; Evaluate a preOrder numeric expression against bound inputs.
;; Grounded atoms are numeric constants; Symbols are input variables;
;; Expressions dispatch on the head operator.
;; (: evalNumeric (-> $expr (List ($l $v)) Number))
(= (evalNumeric $expr $pairs)
   (case (get-metatype $expr)
     ((Grounded $expr)
      (Symbol (lookupNumeric $expr $pairs))
      (Expression
        (case (car-atom $expr)
          ((+ (sumEvalNumeric (cdr-atom $expr) $pairs))
           (* (prodEvalNumeric (cdr-atom $expr) $pairs))
           ($_op (Error $expr "Unsupported operator in numeric expression"))))))))
