"""Durable, typed JSON checkpoints; no executable pickle payloads."""

import json
import os
import random

import protocol_version
import responder_control as rc


def encode(value):
    if isinstance(value, dict):
        return {"type": "dict", "items": [[encode(k), encode(v)] for k, v in value.items()]}
    if isinstance(value, (list, tuple, set)):
        return {"type": type(value).__name__, "items": [encode(v) for v in value]}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"checkpoint cannot serialize {type(value).__name__}")


def decode(value):
    if not isinstance(value, dict):
        return value
    kind, items = value["type"], value["items"]
    if kind == "dict":
        return {decode(k): decode(v) for k, v in items}
    factories = {"list": list, "tuple": tuple, "set": set}
    return factories[kind](decode(v) for v in items)


def save(path, evolution, continuation, request, agent_context=None):
    if continuation is None:
        raise ValueError("pause checkpoint requires a native continuation")
    doc = {"version": 1, "protocol": protocol_version.compute(),
           "rng_state": encode(random.getstate()), "evolution": encode(evolution),
           "continuation": encode(continuation), "request": request,
           "agent_context": agent_context or {"history": [], "summaries": []}}
    rc.write_json_atomic(path, doc, fsync=True)
    return doc


def restore(path):
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    if doc.get("version") != 1 or doc.get("protocol") != protocol_version.compute():
        raise ValueError("checkpoint version/protocol differs from this implementation")
    evolution = decode(doc["evolution"])
    continuation = decode(doc["continuation"])
    random.setstate(decode(doc["rng_state"]))
    return evolution, continuation, doc


def context_snapshot(run_dir, run_seq):
    """Persist the exact conversation artifacts rather than only their paths."""
    records = []
    for section in ("traces", "context", "summaries"):
        root = os.path.join(run_dir, section, f"run-{run_seq}")
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            path = os.path.join(root, name)
            if os.path.isfile(path) and name.endswith((".json", ".md", ".txt")):
                with open(path, encoding="utf-8") as fh:
                    records.append({"path": os.path.relpath(path, run_dir), "text": fh.read()})
    return {"artifacts": records}


def restore_context(run_dir, snapshot):
    root = os.path.realpath(run_dir)
    for artifact in snapshot.get("artifacts", []):
        path = os.path.realpath(os.path.join(root, artifact["path"]))
        if os.path.commonpath([path, root]) != root:
            raise ValueError("checkpoint context path escapes the run directory")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "w", encoding="utf-8") as fh:
            fh.write(artifact["text"])
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(path + ".tmp", path)
