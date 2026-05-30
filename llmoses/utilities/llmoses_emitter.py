"""LLMOSES state emitter — Python-owned file I/O (v0)."""
import os, sys

_OVERRIDE = os.environ.get("LLMOSES_STATE_LOG")
if _OVERRIDE:
    _LOG_PATH = os.path.abspath(_OVERRIDE)
else:
    _THIS_DIR    = os.path.dirname(os.path.abspath(__file__))  # .../llmoses/utilities
    _LLMOSES_DIR = os.path.dirname(_THIS_DIR)                  # .../llmoses
    _LOG_DIR     = os.path.join(_LLMOSES_DIR, "outputs", "states")
    _LOG_PATH    = os.path.join(_LOG_DIR, "llmoses-state.log")

os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)
_FH = open(_LOG_PATH, "a", buffering=1, encoding="utf-8")

def emit_state(gen_index, remaining):
    g = int(gen_index)
    r = int(remaining)
    _FH.write(f"LLMOSES_STATE gen {g} remaining {r}\n")
    return 0

def log_path():
    return _LOG_PATH
