#!/usr/bin/env python3
"""Bounded live estimator for one LLMOSES generation (option and baseline).

The provider only emits slot values. This module owns prompt rendering,
provider dispatch (through provider_adapter — one provider path, W-13),
JSON extraction, the W-14 retry budget, final value-level salvage (W-18,
recorded), and the W-5 status/outcome stamped on every document. It never
raises out of estimate().

Separation of duties (plan §1.4): the estimator REPORTS accurately — status,
error class, attempts, salvage, coverage, context — and never decides what a
failure means for the run. MOSES (plan §1.3) continues only on 200/204; the
supervisor decides escalation.

Status mapping:
  200  values assembled into guidance
  204  provider legitimately supplied no values (deliberate abstention)
  422  input unusable (capture_status.ok false, alphabet missing, slot
       enumeration failed) — no provider call is made
  500  malformed / schema-violating output after the retry, nothing salvaged
  503  provider error (auth / quota / rate limit / moderation / network /
       unknown) after its class budget
  504  provider timed out after its class budget
"""

import json
import math
import os
import time

import provider_adapter
import response_template
import utility_schema

try:
    import protocol_version as _pv
except Exception:  # pragma: no cover - protocol module is optional at import
    _pv = None

_DEFAULT_MODEL = "gpt-5.5"
_DEFAULT_EFFORT = "medium"
# W-16 calibration: recorded per-attempt wall times under llmoses/outputs/
# live-demo/*/traces (n=14, gpt-5.5 medium, coverage=full): median 12.1 s,
# p90 15.0 s, max 18.2 s. 120 s is the tail plus a wide margin.
_DEFAULT_TIMEOUT_S = 120.0
# W-14: retry budget is ONE. LLMOSES_LIVE_RETRIES caps the per-class budget
# (it cannot raise a class above its table value).
_DEFAULT_RETRIES = 1
_DEFAULT_BACKOFF_S = 5.0
_ROW_CAP = 30
CONTEXT_STRATEGY = "per_generation"   # W-22: the bounded path has no continuity


class TimeoutInvariantError(RuntimeError):
    pass


def timeout_budget_s():
    """Worst-case wall time this estimator can spend on one generation."""
    timeout_s = _env_float("LLMOSES_LIVE_TIMEOUT_S", _DEFAULT_TIMEOUT_S)
    retries = max(0, _env_int("LLMOSES_LIVE_RETRIES", _DEFAULT_RETRIES))
    max_budget = max(provider_adapter.RETRY_BUDGET.values())
    attempts = 1 + min(retries, max_budget)
    backoff = _env_float("LLMOSES_LIVE_BACKOFF_S", _DEFAULT_BACKOFF_S)
    return timeout_s * attempts + backoff * max(0, attempts - 1)


def check_timeout_invariant(response_timeout_s):
    """W-16: assert LIVE_TIMEOUT_S x (RETRIES+1) < RESPONSE_TIMEOUT_S.
    MOSES would otherwise abandon the generation before the estimator can
    answer. Raises TimeoutInvariantError; the caller fails fast."""
    if response_timeout_s is None:
        return None
    try:
        rt = float(response_timeout_s)
    except (TypeError, ValueError):
        return None
    budget = timeout_budget_s()
    if not budget < rt:
        raise TimeoutInvariantError(
            f"estimator worst case {budget:.1f}s (LLMOSES_LIVE_TIMEOUT_S x "
            f"attempts + backoff) is not below LLMOSES_RESPONSE_TIMEOUT_S="
            f"{rt:.1f}s; MOSES would time out before the estimate arrives")
    return budget


def _outcome(attempts, salvage=None, coverage=None, error_class=None,
             detail=None, context_chars=None):
    oc = {"attempts": int(attempts), "retried": attempts > 1,
          "context": {"strategy": CONTEXT_STRATEGY,
                      "chars": int(context_chars or 0),
                      "compressed": False, "dropped": []}}
    if salvage is not None:
        oc["salvage"] = salvage
    if coverage is not None:
        oc["coverage"] = coverage
    if error_class is not None:
        oc["error_class"] = error_class
    if detail:
        oc["detail"] = str(detail)[:500]
    if _pv is not None:
        try:
            oc["protocol_version"] = _pv.compute()
        except Exception:
            pass
    return oc


def _neutral(slots, run_config, status=204, outcome=None):
    return response_template.assemble(slots or {}, {}, run_config, decline=True,
                                      status=status, outcome=outcome)


def _bare_neutral(status, outcome):
    doc = utility_schema._empty_doc(True)
    doc["status"] = status
    if outcome is not None:
        doc["outcome"] = outcome
    return doc


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


def _salvage_values(slots, values, run_config, trace, status=200,
                    outcome=None):
    """W-18: drop values until the document assembles; the drop count is a
    RECORDED outcome (outcome.salvage = {requested, survived}), never a
    silent repair."""
    work = dict(values or {})
    requested = len(work)
    dropped = trace.setdefault("dropped_keys", [])
    for key in sorted(list(work)):
        if key not in slots:
            dropped.append({"key": key, "reason": "unknown slot"})
            work.pop(key, None)
    while work:
        try:
            oc = dict(outcome or {})
            oc["salvage"] = {"requested": requested, "survived": len(work)}
            return response_template.assemble(slots, work, run_config,
                                              status=status, outcome=oc)
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
    trace["salvage"] = {"requested": requested, "survived": 0}
    return None


def _coverage(slots, values):
    mode = os.environ.get("LLMOSES_LIVE_COVERAGE", "sparse")
    return {"mode": mode,
            "requested": len(slots) if mode == "full" else None,
            "supplied": len(values or {})}


def _input_problem(state, run_config):
    """W-5 422: is the input usable at all?"""
    cs = state.get("capture_status") if isinstance(state, dict) else None
    if isinstance(cs, dict) and cs.get("ok") is False:
        return ("capture_status.ok is false: failed sections "
                f"{cs.get('failed_sections')}")
    if not isinstance(run_config, dict) or not (run_config.get("atom_alphabet")
                                                or {}).get("atoms"):
        return "run_config.atom_alphabet is missing or empty"
    return None


def estimate(state, run_config, gen):
    """Return (UtilityResponse, trace_extras) for one generation.

    Every document carries `status` and `outcome`; no exception escapes.
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
        "context_strategy": CONTEXT_STRATEGY,
        "audit_reasoning": [
            "live estimator rendered closed slot schema and requested flat JSON values",
        ],
    }
    slots = {}
    attempts = 0
    prompt_chars = 0
    try:
        problem = _input_problem(state, run_config)
        if problem is not None:
            trace["status"] = 422
            trace["error_class"] = "input"
            trace["neutral_reason"] = problem
            oc = _outcome(1, error_class="input", detail=problem)
            try:
                slots = response_template.build_slots(state, run_config)
                return _neutral(slots, run_config, 422, oc), trace
            except Exception:
                return _bare_neutral(422, oc), trace
        try:
            slots = response_template.build_slots(state, run_config)
            schema = response_template.json_schema(slots)
        except Exception as e:
            detail = f"slot enumeration failed: {e!r}"
            trace["status"] = 422
            trace["error_class"] = "input"
            trace["neutral_reason"] = detail
            return _bare_neutral(422, _outcome(1, error_class="input",
                                               detail=detail)), trace
        trace["slot_count"] = len(slots)
        timeout_s = _env_float("LLMOSES_LIVE_TIMEOUT_S", _DEFAULT_TIMEOUT_S)
        retry_cap = max(0, _env_int("LLMOSES_LIVE_RETRIES", _DEFAULT_RETRIES))
        backoff_s = _env_float("LLMOSES_LIVE_BACKOFF_S", _DEFAULT_BACKOFF_S)
        retry_error = None
        last_values = None
        last_err = None
        budget = None          # retries allowed for the class of the last error
        while True:
            attempts += 1
            prompt = _render_prompt(state, run_config, gen, slots, schema,
                                    retry_error)
            prompt_chars = max(prompt_chars, len(prompt))
            if attempts == 1:
                trace["prompt"] = prompt
            t0 = time.time()
            err = None
            try:
                raw = provider_adapter.invoke(prompt, trace["model"],
                                              trace["effort"], timeout_s,
                                              output_schema=schema)
                trace["wall_time_s"].append(round(time.time() - t0, 6))
                trace["raw_provider_outputs"].append(raw)
                try:
                    values = _parse_values(raw)
                except ValueError as e:
                    raise provider_adapter.ProviderError(
                        "malformed", str(e), attempt_output=raw) from e
                last_values = values
                try:
                    if not values:
                        # A legitimately empty payload is a deliberate
                        # abstention, not guidance with nothing in it.
                        oc = _outcome(attempts, coverage=_coverage(slots, values),
                                      context_chars=prompt_chars)
                        trace["status"] = 204
                        return _neutral(slots, run_config, 204, oc), trace
                    oc = _outcome(attempts, coverage=_coverage(slots, values),
                                  context_chars=prompt_chars)
                    doc = response_template.assemble(slots, values, run_config,
                                                     outcome=oc)
                except (KeyError, ValueError, AssertionError) as e:
                    raise provider_adapter.ProviderError(
                        "schema", str(e), attempt_output=raw) from e
                trace["status"] = 200
                return doc, trace
            except provider_adapter.ProviderError as e:
                err = e
            if len(trace["wall_time_s"]) < attempts:
                trace["wall_time_s"].append(round(time.time() - t0, 6))
            last_err = err
            trace["attempt_errors"].append({"attempt": attempts,
                                            "class": err.error_class,
                                            "retryable": err.retryable,
                                            "error": str(err.detail)[:2000]})
            if budget is None:
                budget = provider_adapter.budget_for(err.error_class, retry_cap)
            if not err.retryable or attempts > budget:
                break
            retry_error = err.detail if err.error_class in ("malformed",
                                                            "schema") else None
            if err.error_class == "rate_limit" and backoff_s > 0:
                time.sleep(backoff_s)

        # Retry budget spent. Malformed / schema failures may still carry
        # usable values: salvage them, recorded (W-18).
        error_class = last_err.error_class if last_err else "provider_error"
        trace["error_class"] = error_class
        if last_values and error_class in ("malformed", "schema"):
            oc = _outcome(attempts, coverage=_coverage(slots, last_values),
                          error_class=error_class, detail=last_err.detail,
                          context_chars=prompt_chars)
            salvaged = _salvage_values(slots, last_values, run_config, trace,
                                       outcome=oc)
            if salvaged is not None:
                trace["status"] = 200
                return salvaged, trace
        status = provider_adapter.status_for(error_class)
        trace["status"] = status
        trace["neutral_reason"] = (f"{error_class}: retry budget spent after "
                                   f"{attempts} attempt(s)")
        oc = _outcome(attempts, error_class=error_class,
                      detail=last_err.detail if last_err else None,
                      context_chars=prompt_chars,
                      salvage=trace.get("salvage"))
        return _neutral(slots, run_config, status, oc), trace
    except Exception as e:
        trace["unexpected_exception"] = repr(e)
        trace["status"] = 500
        oc = _outcome(max(1, attempts), error_class="responder_failure",
                      detail=repr(e), context_chars=prompt_chars)
        try:
            return _neutral(slots, run_config, 500, oc), trace
        except Exception:
            return _bare_neutral(500, oc), trace
