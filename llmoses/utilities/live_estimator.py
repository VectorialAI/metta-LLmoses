#!/usr/bin/env python3
"""Live constrained-generation estimator for one LLMOSES generation.

The provider only emits slot values. This module owns prompt rendering,
provider dispatch, JSON extraction, retries, final value-level salvage, and
neutral-decline fallback. It never raises out of estimate().
"""

import json
import math
import os
import shlex
import subprocess
import tempfile
import time

import response_template

_DEFAULT_MODEL = "gpt-5.5"
_DEFAULT_EFFORT = "medium"
_DEFAULT_TIMEOUT_S = 240.0
_DEFAULT_RETRIES = 2
_ROW_CAP = 30


def _neutral(slots, run_config):
    return response_template.assemble(slots or {}, {}, run_config, decline=True)


def _as_float(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    if not math.isfinite(v):
        return None
    return float(v)


def _compact_json(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _score_of_member(m):
    return (m.get("cscore") or {}).get("penalized_score")


def _evidence_digest(state, cap=_ROW_CAP):
    members = []
    for m in (state.get("metapopulation") or {}).get("members") or []:
        pid = m.get("program_id")
        if pid is None:
            continue
        members.append({"program_id": pid,
                        "penalized_score": _score_of_member(m)})
    def score_key(row):
        score = _as_float(row.get("penalized_score"))
        return (score is not None, score if score is not None else float("-inf"))
    members = sorted(members, key=score_key, reverse=True)[:cap]

    ev = state.get("atom_evidence") or {}
    appearances = (ev.get("atom_appearances") or [])[:cap]
    cooccurrences = (ev.get("realized_cooccurrences") or [])[:cap]
    return _compact_json({
        "top_metapopulation": members,
        "atom_appearances": appearances,
        "realized_cooccurrences": cooccurrences,
    })


def _slots_table(slots):
    lines = ["slot_key | domain | meta"]
    for key in sorted(slots):
        spec = slots[key]
        domain = spec.get("domain")
        if spec.get("enum"):
            domain = f"{domain}:{','.join(str(v) for v in spec['enum'])}"
        meta = spec.get("meta") or {}
        keep = {}
        for k in ("penalized_score", "observed_count", "newborn_default"):
            if k in meta:
                keep[k] = meta[k]
        lines.append(f"{key} | {domain} | {_compact_json(keep)}")
    return "\n".join(lines)


def _prompt_path():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", "skills",
                                        "ESTIMATOR_PROMPT.md"))


def _render_prompt(state, run_config, gen, slots, schema, retry_error=None):
    with open(_prompt_path(), "r", encoding="utf-8") as fh:
        template = fh.read()
    prompt = template
    replacements = {
        "{generation}": str(gen),
        "{coverage}": os.environ.get("LLMOSES_LIVE_COVERAGE", "sparse"),
        "{slots_table}": _slots_table(slots),
        "{json_schema}": json.dumps(schema, indent=2, sort_keys=True),
        "{evidence_digest}": _evidence_digest(state),
    }
    for token, value in replacements.items():
        prompt = prompt.replace(token, value)
    if retry_error is not None:
        prompt += ("\n\nRETRY\n"
                   "Your previous output failed the constrained slot-value "
                   "gate with this exact error. Return only a corrected flat "
                   f"JSON object.\n{retry_error}\n")
    return prompt


def _extract_json_object(text):
    if not isinstance(text, str):
        raise ValueError("provider output is not text")
    start = text.find("{")
    if start < 0:
        raise ValueError("provider output contained no JSON object")
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise ValueError("provider output JSON object was not closed")


def _parse_values(raw):
    try:
        values = json.loads(_extract_json_object(raw))
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON parse failure: {e}") from e
    if not isinstance(values, dict):
        raise ValueError("values payload must be a JSON object")
    for k, v in values.items():
        if not isinstance(k, str):
            raise ValueError("values payload keys must be strings")
        if isinstance(v, (dict, list)):
            raise ValueError(f"{k}: values payload must be flat")
    return values


def _env_float(name, default):
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return float(default)


def _env_int(name, default):
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return int(default)


def _run_provider(prompt, model, effort, timeout_s):
    live_cmd = os.environ.get("LLMOSES_LIVE_CMD")
    if live_cmd:
        cmd = shlex.split(live_cmd)
        if not cmd:
            raise RuntimeError("LLMOSES_LIVE_CMD was empty")
        proc = subprocess.run(cmd, input=prompt, text=True,
                              capture_output=True, timeout=timeout_s,
                              check=False)
        if proc.returncode != 0:
            raise RuntimeError("provider command exited "
                               f"{proc.returncode}: {proc.stderr[:1000]}")
        return proc.stdout

    with tempfile.TemporaryDirectory(prefix="llmoses-live-codex-") as td:
        out_path = os.path.join(td, "last-message.txt")
        cmd = [
            "codex", "exec",
            "-m", model,
            "-c", f"model_reasoning_effort={effort}",
            "--sandbox", "read-only",
            "--skip-git-repo-check",
            "--output-last-message", out_path,
            "-",
        ]
        proc = subprocess.run(cmd, input=prompt, text=True,
                              capture_output=True, timeout=timeout_s,
                              cwd=td, check=False)
        if proc.returncode != 0:
            raise RuntimeError("codex exec exited "
                               f"{proc.returncode}: {proc.stderr[:1000]}")
        with open(out_path, "r", encoding="utf-8") as fh:
            return fh.read()


def _bad_key_from_error(err):
    text = str(err)
    if "unknown slot:" in text:
        part = text.split("unknown slot:", 1)[1].strip()
        if part and part[0] in ("'", '"'):
            quote = part[0]
            end = part.find(quote, 1)
            if end > 1:
                return part[1:end]
        return part.strip("'\"")
    if ":" in text:
        return text.split(":", 1)[0]
    return None


def _salvage_values(slots, values, run_config, trace):
    work = dict(values or {})
    dropped = trace.setdefault("dropped_keys", [])
    for key in sorted(list(work)):
        if key not in slots:
            dropped.append({"key": key, "reason": "unknown slot"})
            work.pop(key, None)
    while work:
        try:
            return response_template.assemble(slots, work, run_config)
        except (KeyError, ValueError, AssertionError) as e:
            bad = None
            for key in sorted(work):
                try:
                    response_template.assemble(slots, {key: work[key]},
                                               run_config)
                except (KeyError, ValueError, AssertionError) as single:
                    bad = key
                    reason = str(single)
                    break
            if bad is None:
                parsed = _bad_key_from_error(e)
                if parsed in work:
                    bad = parsed
                    reason = str(e)
            if bad is None:
                bad = sorted(work)[0]
                reason = str(e)
            dropped.append({"key": bad, "reason": reason})
            work.pop(bad, None)
    return None


def estimate(state, run_config, gen):
    """Return (UtilityResponse, trace_extras) for one generation.

    All failures degrade to a valid neutral decline; no exception escapes.
    """
    trace = {
        "live_estimator": True,
        "raw_provider_outputs": [],
        "attempt_errors": [],
        "dropped_keys": [],
        "model": os.environ.get("LLMOSES_LIVE_MODEL", _DEFAULT_MODEL),
        "effort": os.environ.get("LLMOSES_LIVE_EFFORT", _DEFAULT_EFFORT),
        "provider": ("LLMOSES_LIVE_CMD" if os.environ.get("LLMOSES_LIVE_CMD")
                     else "codex_exec"),
        "wall_time_s": [],
        "coverage": os.environ.get("LLMOSES_LIVE_COVERAGE", "sparse"),
        "audit_reasoning": [
            "live estimator rendered closed slot schema and requested flat JSON values",
        ],
    }
    slots = {}
    try:
        slots = response_template.build_slots(state, run_config)
        schema = response_template.json_schema(slots)
        trace["slot_count"] = len(slots)
        timeout_s = _env_float("LLMOSES_LIVE_TIMEOUT_S", _DEFAULT_TIMEOUT_S)
        retries = max(0, _env_int("LLMOSES_LIVE_RETRIES", _DEFAULT_RETRIES))
        retry_error = None
        last_values = None
        for attempt in range(retries + 1):
            prompt = _render_prompt(state, run_config, gen, slots, schema,
                                    retry_error)
            if attempt == 0:
                trace["prompt"] = prompt
            t0 = time.time()
            try:
                raw = _run_provider(prompt, trace["model"], trace["effort"],
                                    timeout_s)
                trace["wall_time_s"].append(round(time.time() - t0, 6))
                trace["raw_provider_outputs"].append(raw)
                values = _parse_values(raw)
                last_values = values
                doc = response_template.assemble(slots, values, run_config)
                return doc, trace
            except subprocess.TimeoutExpired as e:
                trace["wall_time_s"].append(round(time.time() - t0, 6))
                err = f"provider timeout after {timeout_s}s: {e}"
            except (KeyError, ValueError, AssertionError, RuntimeError) as e:
                if len(trace["wall_time_s"]) <= attempt:
                    trace["wall_time_s"].append(round(time.time() - t0, 6))
                err = str(e)
            trace["attempt_errors"].append({"attempt": attempt + 1,
                                            "error": err})
            retry_error = err

        if last_values is not None:
            salvaged = _salvage_values(slots, last_values, run_config, trace)
            if salvaged is not None:
                return salvaged, trace
        trace["neutral_reason"] = "provider retries exhausted"
        return _neutral(slots, run_config), trace
    except Exception as e:
        trace["unexpected_exception"] = repr(e)
        try:
            return _neutral(slots, run_config), trace
        except Exception:
            return {
                "pass": True,
                "sampling_temperature": None,
                "exemplar_utilities": [],
                "atom_utility_prior": [],
                "combination_synergy": [],
                "feature_utility_levers": None,
                "culling_utilities": [],
                "complexity_ratio_delta": None,
                "comparator_bias": None,
            }, trace
