;; LLMOSES state emitter wrapper.
;; File I/O is owned by the Python module llmoses_emitter.py (same
;; directory). See that file for path-resolution and handle-lifecycle
;; notes. MeTTa's role here is minimal: import the module and delegate.
;;
;; llmoses/utilities/ is on PYTHONPATH (Dockerfile ENV), so the bare
;; module name resolves from any CWD — no ../../ prefix needed.

!(import! &self "llmoses_emitter.py")

;; Canary: evaluated at import time. Emits the log path on success.
;; If PYTHONPATH does not include llmoses/utilities/ this produces no
;; output — a visible sign that emitState will silently be a no-op.
!(py-call (llmoses_emitter.log_path))
!(py-call (llmoses_emitter.run_dir))

;; $genIndex : ascending, human-facing generation number (1-based)
;; $remaining: the loop's native descending counter ($maxGen)
;; (: emitState (-> Number Number Number))
(= (emitState $genIndex $remaining)
   (py-call (llmoses_emitter.emit_state $genIndex $remaining)))

;; Python fans out into metapop/deme/action channels.
;; $genIndex  : ascending 1-based generation number
;; $remaining : the loop's native descending counter ($maxGen)
;; $popSize   : OS.length of the metapopulation going into this generation
;; $bestScore : penalized score of the current top exemplar
;; $demeSize  : number of scored instances in the optimized deme this gen
;; (: emitGen (-> Number Number Number Number Number Number))
(= (emitGen $genIndex $remaining $popSize $bestScore $demeSize)
   (py-call (llmoses_emitter.emit_gen $genIndex $remaining $popSize $bestScore $demeSize)))

;; Called once at the top of every runMoses invocation to open a fresh
;; per-run subdirectory for step files (run-1/, run-2/, …). Without this,
;; all runMoses calls within the same process write gen-1 of run A and
;; gen-1 of run B into the same step-1.txt.
;; (: emitNewRun (-> Number))
(= (emitNewRun)
   (py-call (llmoses_emitter.new_run)))
