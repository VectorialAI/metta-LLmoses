"""W-28 protocol versioning.

In the agent-orchestrated path the skill IS the experimental protocol:
undeclared drift in the skill text, the tool definitions, or the agent
configuration between runs silently invalidates comparisons, exactly as an
undeclared prompt change would. This module derives one identifier from the
protocol-bearing files and lets an experiment PIN it:

  * compute()            -> "llmoses-p<MAJOR>+<12 hex>" (content digest)
  * check_pin(version)   -> raises ProtocolPinError when LLMOSES_PROTOCOL_PIN
                            is set and differs (responders refuse to start)

Responders record the identifier in CONTROL/responder (run metadata) and in
every response `outcome.protocol_version`; MOSES surfaces both in
terminal.json (`protocol_version`, `protocol_versions_seen`) and flags
`protocol_drift` when more than one identifier is seen within a run.

Bump PROTOCOL_MAJOR on a deliberate, incompatible protocol change; the digest
half moves on its own whenever any covered file changes.
"""

import glob
import hashlib
import os
import sys

PROTOCOL_MAJOR = 2

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_LLMOSES_DIR = os.path.dirname(_THIS_DIR)

# Relative to the llmoses/ directory. Globs; missing entries are skipped.
COVERED = (
    "skills/*.md",
    "agent-configs/*/*.md",
    "agent-configs/*.md",
    "utilities/agent_tools.py",
    "utilities/responder_control.py",
    "utilities/llmoses_watcher.py",
    "utilities/live_estimator.py",
    "utilities/provider_adapter.py",
    "utilities/response_template.py",
    "utilities/utility_schema.py",
    "utilities/supervisor.py",
    "utilities/protocol_version.py",
    # the MOSES-side half of the protocol: ingest policy, fence, abort, and
    # the generation application point
    "utilities/state_builder.py",
    "utilities/lever_policy.py",
    "utilities/lever_config.py",
    "utilities/conditional_policy.py",
    "utilities/checkpointing.py",
    "utilities/call_paths.py",
    # the Call 4 state-document emitter: its field set is agent-facing contract
    "utilities/atom_evidence.py",
    "utilities/boundary.py",
    "utilities/context_docs.py",
    "utilities/context_doc_templates/*.md",
    "scoring/cscore.metta",
    "metapopulation/*.metta",
    "deme/merge-demes.metta",
    "representation/build-logical.metta",
    "representation/add-logical-knobs.metta",
    "representation/sample-logical-perms.metta",
    "wrapper/state-builder.metta",
    "deme/expand-deme.metta",
)


class ProtocolPinError(RuntimeError):
    pass


def covered_files(llmoses_dir=None):
    root = llmoses_dir or _LLMOSES_DIR
    out = []
    for pattern in COVERED:
        out.extend(glob.glob(os.path.join(root, pattern)))
    return sorted(set(os.path.abspath(p) for p in out if os.path.isfile(p)))


def compute(llmoses_dir=None):
    root = llmoses_dir or _LLMOSES_DIR
    h = hashlib.sha256()
    h.update(f"major={PROTOCOL_MAJOR}\n".encode("utf-8"))
    for path in covered_files(root):
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        h.update(f"file={rel}\n".encode("utf-8"))
        with open(path, "rb") as fh:
            h.update(fh.read())
        h.update(b"\n--\n")
    return f"llmoses-p{PROTOCOL_MAJOR}+{h.hexdigest()[:12]}"


def pinned():
    return os.environ.get("LLMOSES_PROTOCOL_PIN") or None


def check_pin(version=None):
    """Raise ProtocolPinError when the experiment pinned a different
    protocol identifier. Returns the (computed) version otherwise."""
    version = version or compute()
    pin = pinned()
    if pin and pin != version:
        raise ProtocolPinError(
            f"protocol version {version} does not match the pinned "
            f"LLMOSES_PROTOCOL_PIN={pin}; refusing to respond under an "
            "undeclared protocol change")
    return version


if __name__ == "__main__":
    v = compute()
    if "--files" in sys.argv:
        for p in covered_files():
            print(p)
    print(v)
    try:
        check_pin(v)
    except ProtocolPinError as e:
        print(f"PIN MISMATCH: {e}", file=sys.stderr)
        sys.exit(1)
