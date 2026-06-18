;; Gives an instance a composite score. 
;; Params:
;;   $rep: The representation object
;;   $inst: The instance we want to evaluate
;;   $itable: The input table
;;   $complexityRatio: probability parameter
;; Returns:
;;   cScore: Composite score of the instance                      
;; (: complexityBasedScorer (-> Representation Instance (ITable $a) Number Cscore))

;; LLMOSES change: candidate may be a list of trees, one per representation
;; when feature selection is on. Evaluate before scoring to get the tree value.
    (= (complexityBasedScorer $rep $inst $itable $complexityRatio)
      (let*
          (
            ($tree (eval (getCandidate $rep $inst)))
            ($score (getCscore $itable $tree $complexityRatio &bscoreCache))
          )
          $score))
