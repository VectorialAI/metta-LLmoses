;; llmoses/llmoses-tests/strategy_demos_test.metta — classic tic-tac-toe strategy demo.
;;
;; Built on examples/tic-tac-toe/ (game engine, moses-player, strategy scoring).
;; Run via:  ./run_moses_demo.sh demo ttt
;;
;; Fast strategy regression lives in strategy_test.metta / run_strategy_smoke_test.sh.

!(import! &self llmoses/llmoses-tests/strategy_test)
!(import! &self llmoses/wrapper/extractors)

;; Watchable demo parameters (longer than smoke fixtures).
(= (classicStrategyDemoMaxGen) 7)
(= (classicStrategyDemoNDeme) 2)
(= (classicStrategyDemoNGames) 10)
(= (classicStrategyDemoComplexityRatio) 3.5)
(= (classicStrategyDemoTargetCscore) (mkCscore 10.0 5 1.43 0.0 6.57))

(= (strategyDemoOpponent $key)
   (case $key
     ((ttt     random-player)
      (ttt-mm  minimax-player))))

(= (runClassicStrategyDemo $key)
   (let* (
     ($opponent (strategyDemoOpponent $key))
     ($_ (println! (StrategyDemo: key= $key opponent= $opponent
                    maxGen= (classicStrategyDemoMaxGen)
                    nDeme= (classicStrategyDemoNDeme)
                    nGames= (classicStrategyDemoNGames))))
     ($result (runMoses
                (classicStrategyDemoMaxGen)
                (classicStrategyDemoTargetCscore)
                5
                (strategyMetaPop)
                0 (classicStrategyDemoNDeme)
                ((classicStrategyDemoNGames) $opponent (classicStrategyDemoComplexityRatio))
                hillClimbing
                100 10 2 1.0
                5 0.004 1000))
     ($_ (println! (StrategyDemoRawResult: $result)))
     ($newR (osToExpression (mapG cleanedExemplar $result) ()))
     ($_ (cut))
   )
   (FinalStrategyResult $newR)))
