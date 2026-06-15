;; DEPRECATED — parity-3 pressure test moved to boolean_pressure_test.metta
;; Run via: ./run_boolean_smoke_test.sh metta parity3
;;          ./run_boolean_smoke_test.sh state parity3-short
;;
;; This file is kept as a pointer only; do not extend it.

!(import! &self llmoses/llmoses-tests/boolean_pressure_test)
!(println! (boolean-pressure-result parity3 (booleanPressureParity3)))
