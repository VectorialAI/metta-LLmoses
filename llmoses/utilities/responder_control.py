"""Responder-side CONTROL/ channel helpers (shared by the watcher, the agent
tool suite and the supervisor). Stdlib only; runs on host or in-container.

Files under <run>/CONTROL/ (records are written atomically — tmp +
os.replace, or a complete file published exclusively with os.link):

  responder   W-24 ownership lock. Declares WHO responds to this run:
              {"mode", "run_id", "owner": {"kind", "pid", "host", "session",
               "label"}, "protocol_version", "protocol_pin",
               "context_strategy", "ts_ms", "released": bool}. claim() and
              release() are serialised under an advisory fcntl.flock on
              CONTROL/responder.lock (kernel-released on holder death), so
              exactly one of any number of concurrent claimants succeeds; a
              second responder is refused unless the record is released or
              LLMOSES_RESPONDER_TAKEOVER=1. (R1: whether MOSES
              EXPECTS a response is declared by the run configuration —
              LLMOSES_AWAIT_RESPONSE / LLMOSES_EXPECT_RESPONSE_GENS — never
              inferred from this file.)

              Agent identity is a SESSION TOKEN minted at claim time and
              bound to this run (`<run_id>.<hex>`): an agent is not one
              process (per-generation sub-agents, one CLI process per tool
              call), so the writing process routinely differs from the
              claiming one. A token minted for another run is rejected.
              This is a COORDINATION mechanism — it prevents accidental
              doubling, dropping or cross-over of responses between
              concurrent sub-processes — NOT an authorization boundary:
              anything with filesystem access can read it. Do not describe
              it as a security control.
  heartbeat   W-3/W-9 level-triggered liveness: {"counter", "ts_ms", "owner"}.
              MOSES asserts only that `counter` ADVANCED (clock-domain free).
              Never written into the ready/response sentinels.
  abort       W-20 responder -> MOSES abort request:
              {"reason", "source", "detail", "ts_ms"}. MOSES exits non-zero
              on its next poll / generation boundary.
  stop        pre-existing watcher stop flag (existence only).
"""

import fcntl
import json
import os
import socket
import threading
import time
import uuid

FSYNC = os.environ.get("LLMOSES_FSYNC", "0") == "1"


def control_dir(run_dir):
    return os.path.join(run_dir, "CONTROL")


def control_path(run_dir, name):
    return os.path.join(control_dir(run_dir), name)


def _now_ms():
    return int(time.time() * 1000)


def write_json_atomic(path, doc, fsync=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True)
        fh.write("\n")
        if FSYNC if fsync is None else fsync:
            fh.flush()
            os.fsync(fh.fileno())
    os.replace(tmp, path)


def read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        return doc if isinstance(doc, dict) else None
    except Exception:
        return None


def owner_record(kind, session=None, label=None):
    return {"kind": kind, "pid": os.getpid(), "host": socket.gethostname(),
            "session": session, "label": label}


def run_identity(run_dir):
    """Stable identity of a run directory: run_meta.json's run_id when the
    emitter wrote one, else the directory basename."""
    meta = read_json(os.path.join(run_dir, "run_meta.json")) or {}
    rid = meta.get("run_id")
    return str(rid) if rid else os.path.basename(os.path.normpath(
        os.path.abspath(run_dir)))


def mint_session(run_dir):
    """R3: a fresh token bound to THIS run. Regenerated at every claim."""
    return f"{run_identity(run_dir)}.{uuid.uuid4().hex}"


def session_matches_run(session, run_dir):
    """A minted token carries its run identity; reject one minted elsewhere.
    Tokens without the prefix (operator-chosen labels) are not run-bound."""
    if not session or "." not in session:
        return True
    prefix = session.rsplit(".", 1)[0]
    return prefix == run_identity(run_dir)


def _session_from_env(session):
    return session or os.environ.get("LLMOSES_RESPONDER_SESSION") or None


def _same_owner(owner, kind=None, session=None):
    """Ownership identity. A long-lived responder (the watcher) is identified
    by (host, pid). An AGENT drives the tool suite through many short-lived
    CLI processes, so its identity is the SESSION token minted at claim time
    (passed as --session or LLMOSES_RESPONDER_SESSION), never a pid."""
    owner = owner or {}
    if kind is not None and owner.get("kind") != kind:
        return False
    session = _session_from_env(session)
    if owner.get("session") and session:
        return owner.get("session") == session
    return (owner.get("pid") == os.getpid()
            and owner.get("host") == socket.gethostname())


class OwnershipConflict(RuntimeError):
    pass


def claim(run_dir, mode, kind, protocol_version=None, context_strategy=None,
          session=None, takeover=None):
    """W-24: declare responder ownership. Returns the record written.
    Raises OwnershipConflict when another live responder holds the run."""
    path = control_path(run_dir, "responder")
    os.makedirs(control_dir(run_dir), exist_ok=True)
    if takeover is None:
        takeover = os.environ.get("LLMOSES_RESPONDER_TAKEOVER", "0") == "1"
    label = None
    if kind == "agent":
        # R3: ALWAYS mint a fresh run-bound token; a caller-supplied value is
        # kept only as a human label, never as the identity. A token minted
        # for a different run must not be able to claim this one.
        provided = _session_from_env(session)
        if provided and not session_matches_run(provided, run_dir):
            raise OwnershipConflict(
                f"session token {provided!r} was minted for another run; "
                "claim mints a fresh token per run")
        label = provided if provided and "." not in provided else None
        session = mint_session(run_dir)
    else:
        session = _session_from_env(session)
    record = {"mode": mode, "run_id": run_identity(run_dir),
              "owner": owner_record(kind, session, label),
              "protocol_version": protocol_version,
              "protocol_pin": os.environ.get("LLMOSES_PROTOCOL_PIN") or None,
              "context_strategy": context_strategy,
              "ts_ms": _now_ms(), "released": False}
    def _conflict(existing):
        # An existing record that cannot be read is treated as HELD (fail
        # safe): never let a transient/corrupt file look like "unowned".
        if existing is None:
            return OwnershipConflict(
                "run directory has a responder record that cannot be read; "
                "refusing to claim (set LLMOSES_RESPONDER_TAKEOVER=1 to take over)")
        if existing.get("released"):
            return None
        if _same_owner(existing.get("owner"), session=session):
            return None
        return OwnershipConflict(
            f"run directory already has a responder: "
            f"{existing.get('mode')} owned by {existing.get('owner')} "
            f"(set LLMOSES_RESPONDER_TAKEOVER=1 to take over)")

    # Acquisition is SERIALISED under an advisory lock on CONTROL/responder.lock
    # (fcntl.flock: released by the kernel when the holder dies, so a claimant
    # that crashes mid-claim leaves no stale lock). Read, decide and publish
    # happen inside the critical section, so no interleaving can let two
    # claimants both succeed — including the released-record re-claim and
    # the takeover case. Pathname-atomic rename/link steps cannot give this
    # guarantee, because a decision taken on one inode could be applied to a
    # record another claimant published in between.
    with _ClaimLock(run_dir):
        if os.path.exists(path):
            existing = read_json(path)
            if not takeover:
                err = _conflict(existing)
                if err is not None:
                    raise err
        write_json_atomic(path, record, fsync=True)
    return record


class _ClaimLock:
    """Exclusive advisory lock around responder-claim acquisition."""

    def __init__(self, run_dir):
        self.path = control_path(run_dir, "responder.lock")
        self.fd = None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        try:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
        finally:
            os.close(self.fd)
            self.fd = None
        return False


def _publish_exclusive(path, doc):
    """Create `path` with the complete document, atomically and exclusively.
    True on success, False when another writer published first."""
    tmp = f"{path}.publish.{os.getpid()}.{uuid.uuid4().hex}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    try:
        os.link(tmp, path)
    except FileExistsError:
        return False
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    try:
        dfd = os.open(os.path.dirname(path), os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass
    return True


def owns(run_dir, kind=None, session=None):
    """True when the caller holds the (unreleased) claim: same (host, pid)
    for a process-bound responder, same session token for an agent."""
    rec = read_json(control_path(run_dir, "responder"))
    if rec is None or rec.get("released"):
        return False
    session = _session_from_env(session)
    if session and not session_matches_run(session, run_dir):
        return False                     # token from another run
    return _same_owner(rec.get("owner"), kind=kind, session=session)


def release(run_dir, session=None, force=False):
    """Mark the claim released (record kept for the audit trail). Only the
    owner may release, unless force=True (operator override)."""
    path = control_path(run_dir, "responder")
    with _ClaimLock(run_dir):
        rec = read_json(path)
        if rec is None:
            return None
        if rec.get("released"):
            return rec
        if not force and not _same_owner(rec.get("owner"), session=session):
            raise OwnershipConflict(
                f"cannot release a claim held by {rec.get('owner')}")
        rec["released"] = True
        rec["released_ts_ms"] = _now_ms()
        write_json_atomic(path, rec, fsync=True)
    return rec


def responder(run_dir):
    """The live ownership record, or None."""
    rec = read_json(control_path(run_dir, "responder"))
    if rec is None or rec.get("released"):
        return None
    return rec


class Heartbeat:
    """W-3 writer: a monotonic counter in CONTROL/heartbeat. beat() writes at
    most every `interval_s`; run as a daemon thread with start() while a
    (possibly reasoning, hence silent) responder is alive."""

    def __init__(self, run_dir, kind, interval_s=None, session=None):
        self.path = control_path(run_dir, "heartbeat")
        self.owner = owner_record(kind, session)
        self.interval_s = float(interval_s if interval_s is not None
                                else os.environ.get("LLMOSES_HEARTBEAT_S", "1.0"))
        self.counter = 0
        self._last = 0.0
        self._stop = threading.Event()
        self._thread = None

    def beat(self, force=False):
        now = time.monotonic()
        if not force and now - self._last < self.interval_s:
            return self.counter
        self.counter += 1
        self._last = now
        try:
            write_json_atomic(self.path, {"counter": self.counter,
                                          "ts_ms": _now_ms(),
                                          "owner": self.owner})
        except Exception:
            pass
        return self.counter

    def _loop(self, alive=None):
        while not self._stop.is_set():
            if alive is not None and not alive():
                return
            self.beat(force=True)
            self._stop.wait(self.interval_s)

    def start(self, alive=None):
        self._thread = threading.Thread(target=self._loop, args=(alive,),
                                        daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)


def request_abort(run_dir, reason, source, detail=None):
    """W-20: ask MOSES to end the run. Idempotent: the FIRST writer wins
    (O_EXCL), so a concurrent second reason never overwrites the evidence."""
    path = control_path(run_dir, "abort")
    os.makedirs(control_dir(run_dir), exist_ok=True)
    doc = {"reason": reason, "source": source, "detail": detail,
           "ts_ms": _now_ms(), "owner": owner_record(source)}
    # R4: evidence — published complete, exclusive and durable (file +
    # directory); a reader can never see a created-but-empty abort record.
    if _publish_exclusive(path, doc):
        return doc
    return read_json(path) or {"reason": "abort_requested",
                               "source": "unknown", "detail": None}


def abort_requested(run_dir):
    return os.path.exists(control_path(run_dir, "abort"))


def pid_alive(pid):
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (TypeError, ValueError):
        return False
    return True
