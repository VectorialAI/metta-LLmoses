#!/usr/bin/env python3
"""Call-local live estimation with persistent context and failure-class retries."""
import json
import math
import os
import time

import protocol_version
import provider_adapter
import response_template
import utility_schema

_DEFAULT_MODEL = "gpt-5.5"
_DEFAULT_EFFORT = "medium"


class TimeoutInvariantError(RuntimeError):
    pass


def _number(name, default, cast=float):
    value = cast(os.environ.get(name, default))
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return value


def timeout_budget_s():
    retries = _number("LLMOSES_LIVE_RETRIES", 1, int)
    timeout = _number("LLMOSES_LIVE_TIMEOUT_S", 120)
    backoff = _number("LLMOSES_LIVE_BACKOFF_S", 5)
    return timeout * (retries + 1) + backoff * (2 ** retries - 1)


def check_timeout_invariant(response_timeout_s):
    if response_timeout_s is not None and timeout_budget_s() >= float(response_timeout_s):
        raise TimeoutInvariantError("provider timeout/retry/backoff budget must be below the per-call response timeout")
    return timeout_budget_s()


def _parse_values(raw):
    # Permit a JSON object in a markdown fence; extra objects/trailing prose are
    # not treated as additional commands. The result is always validated.
    if not isinstance(raw, str):
        raise ValueError("provider output is not text")
    first = raw.find("{")
    if first < 0:
        raise ValueError("provider output contains no JSON object")
    values, unused = json.JSONDecoder().raw_decode(raw[first:])
    if not isinstance(values, dict):
        raise ValueError("provider output must be a values object")
    return values


def _context(state, history):
    strategy = os.environ.get("LLMOSES_CONTEXT_STRATEGY", "full_history")
    if strategy not in ("full_history", "per_generation"):
        raise ValueError("watcher supports full_history or per_generation; use agent_tools for other context strategies")
    records = [{"state": row.get("input_state"),
                "response": row.get("parsed_utility_response"),
                "rationale": row.get("audit_reasoning", [])} for row in history or []]
    if strategy == "per_generation":
        records = []
    cap = _number("LLMOSES_CONTEXT_MAX_CHARS", 0, int)
    truncation = os.environ.get("LLMOSES_CONTEXT_TRUNCATION", "none")
    dropped = []
    while cap and len(json.dumps(records)) > cap and records:
        if truncation != "oldest":
            raise ValueError("context exceeds declared limit; set an explicit oldest truncation policy or raise the limit")
        row = records.pop(0)
        previous = row.get("state") or {}
        dropped.append(f"{previous.get('generation')}-call-{previous.get('call')}")
    return records, {"strategy": strategy, "compressed": bool(dropped), "dropped": dropped,
                     "chars": 0}


def _render_prompt(state, slots, history):
    path = os.path.join(os.path.dirname(__file__), "..", "skills", "ESTIMATOR_PROMPT.md")
    with open(path, encoding="utf-8") as fh:
        guide = fh.read()
    # Arm controls are excluded from the input. Bounds and grammar define the
    # legal surface; b and native/configured temperatures are experimental.
    return (guide + "\n\nPrevious exchanges:\n" + json.dumps(history)
            + "\n\nCurrent call:\n" + json.dumps(state)
            + "\n\nLegal values schema:\n" + json.dumps(response_template.json_schema(slots)))


def estimate(state, run_config, gen=None, history=None):
    trace = {"raw_provider_outputs": [], "attempt_errors": [], "wall_time_s": [],
             "model": os.environ.get("LLMOSES_LIVE_MODEL", _DEFAULT_MODEL),
             "effort": os.environ.get("LLMOSES_LIVE_EFFORT", _DEFAULT_EFFORT),
             "audit_reasoning": ["provider supplied call-specific values"]}
    attempts = 0
    context = {"strategy": "full_history", "chars": 0, "compressed": False, "dropped": []}
    def outcome(error=None):
        result = {"attempts": max(1, attempts), "retried": attempts > 1,
                  "protocol_version": protocol_version.compute(), "context": context}
        if error is not None:
            result.update(error_class=error.error_class, detail=error.detail)
        return result
    try:
        if not state.get("capture_status", {"ok": True}).get("ok"):
            error = provider_adapter.ProviderError("input", "current call capture is incomplete")
            return utility_schema.neutral(state, 422, outcome(error)), trace
        slots = response_template.build_slots(state, run_config)
        records, context = _context(state, history)
        prompt = _render_prompt(state, slots, records)
        context["chars"] = len(prompt)
        trace["prompt"] = prompt
        trace["context_strategy"] = context["strategy"]
        retries = _number("LLMOSES_LIVE_RETRIES", 1, int)
        timeout = _number("LLMOSES_LIVE_TIMEOUT_S", 120)
        backoff = _number("LLMOSES_LIVE_BACKOFF_S", 5)
        while True:
            attempts += 1
            start = time.monotonic()
            try:
                raw = provider_adapter.invoke(prompt, trace["model"], trace["effort"], timeout,
                                              response_template.json_schema(slots))
                trace["raw_provider_outputs"].append(raw)
                try:
                    values = _parse_values(raw)
                except (ValueError, json.JSONDecodeError) as exc:
                    raise provider_adapter.ProviderError("malformed", str(exc)) from exc
                good, drops = {}, []
                for key, value in values.items():
                    try:
                        response_template.assemble(slots, {key: value})
                        good[key] = value
                    except (KeyError, TypeError, ValueError) as exc:
                        drops.append({"key": key, "reason": str(exc)})
                oc = outcome()
                oc["coverage"] = {"mode": "sparse", "requested": len(slots), "supplied": len(good)}
                if drops:
                    oc["salvage"] = {"requested": len(values), "survived": len(good)}
                trace["dropped_keys"] = drops
                if values and not good:
                    return utility_schema.neutral(state, 500, {
                        **oc, "error_class": "schema", "detail": str(drops)[:1000]}), trace
                return response_template.assemble(slots, good, decline=not bool(good), outcome=oc), trace
            except provider_adapter.ProviderError as error:
                trace["attempt_errors"].append(error.as_doc())
                if not error.retryable or attempts > retries:
                    return utility_schema.neutral(state, provider_adapter.status_for(error.error_class),
                                                   outcome(error)), trace
                time.sleep(backoff * (2 ** (attempts - 1)))
            finally:
                trace["wall_time_s"].append(time.monotonic() - start)
    except (KeyError, TypeError, ValueError) as exc:
        # Invalid harness configuration/input is persistent, distinct from
        # semantic errors in an otherwise successful model response.
        error = provider_adapter.ProviderError("configuration", str(exc))
        return utility_schema.neutral(state, 503, outcome(error)), trace
