;; llmoses/llmoses-tests/probe_block_test.metta
;;
;; Phase II throwaway probe (GATE before the blocking-handshake foothold).
;; Answers three load-bearing unknowns at once, with nothing else in the way:
;;   1. does a seconds-long blocking py-call return control to the reduction?
;;   2. does the returned literal 0 resp-binding ($_resp) reduce cleanly?
;;   3. does the let* reduction continue past it?
;;
;; Run:  run.sh llmoses/llmoses-tests/probe_block_test.metta
;; PASS: prints "before-block", pauses ~3s, prints (after-block 0), clean exit.
;; Delete this file (and probe.py) once the foothold is proven.

!(import! &self "probe.py")

(= (probeBlock)
   (let* (
     ($_a    (println! before-block))
     ($_resp (py-call (probe.block_n 3)))
     ($_b    (println! (after-block $_resp)))
   ) $_resp))

!(probeBlock)
