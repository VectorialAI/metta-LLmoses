;; Gives an instance a composite score. 
;; Params:
;;   $rep: The representation object
;;   $inst: The instance we want to evaluate
;;   $itable: The input table
;;   $complexityRatio: probability parameter
;; Returns:
;;   cScore: Composite score of the instance                      
; (: complexityBasedScorer (-> Representation Instance (ITable $a) Number Cscore))

;;llmoses change: candidate may now be a list of trees (one per rep when FS is on), so we evaluate to get the actual tree(s), and is wrapped to affect import order cohesion
    (= (complexityBasedScorer $rep $inst $itable $complexityRatio)
      (let*
          (
            ($tree (eval (getCandidate $rep $inst)))
            ($score (getCscore $itable $tree $complexityRatio &bscoreCache))
          )
          $score))
