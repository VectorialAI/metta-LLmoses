;;;;;;;;;;;;;;;;;;;;;; LLMOSES State Emitter ;;;;;;;;;;;;;;;;;;;;;;
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

;; $genIndex : ascending, human-facing generation number (1-based)
;; $remaining: the loop's native descending counter ($maxGen)
;; (: emitState (-> Number Number Number))
(= (emitState $genIndex $remaining)
   (py-call (llmoses_emitter.emit_state $genIndex $remaining)))
