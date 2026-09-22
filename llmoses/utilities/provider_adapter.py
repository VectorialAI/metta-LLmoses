"""W-13 provider adapter: one provider path, structured error reporting.

`codex exec` exit codes carry no class information and are not under our
control, so classification happens here, against the WHOLE of stderr (the
first ~500 characters are plugin-cache / interface warnings; the diagnostic
error sits at the tail). Every provider failure surfaces as a ProviderError
carrying a structured error document {class, code, retryable, detail}; the
estimator decides retries from `class` alone (W-14 budget table) and reports
the class upward in the response `outcome` — the supervisor decides what to
do about it. An UNKNOWN class is non-retryable and reported, so incomplete
knowledge fails safe.

Two provider paths share this module (there used to be two with different
error fidelity):

  * LLMOSES_LIVE_CMD — a shell command that reads the prompt on stdin and
    prints the answer on stdout (offline tests, stubs, alternate providers).
    A non-zero exit is classified from its stderr exactly like codex, which
    is how failure injection reaches the estimator without a network.
  * codex exec — the default; the rendered prompt goes in on stdin, the
    per-call closed JSON schema goes in via --output-schema (W-5
    constrained generation), and the final message comes back through
    --output-last-message.

Verified signatures (probe Part E): auth -> exit 1 with `401 Unauthorized`,
`invalid_api_key`; network -> exit 1 with `Reconnecting... N/5` then `stream
disconnected before completion`. Quota / 429 were not characterised and are
matched conservatively; quota is checked BEFORE rate limit because provider
quota errors also carry a 429 and the two must not be collapsed (quota is
terminal, rate limit is transient).
"""

import json
import os
import re
import shlex
import subprocess
import tempfile

# class -> (http-like code, retryable at OUR layer)
ERROR_CLASSES = {
    "auth": (401, False),
    "quota": (402, False),
    "rate_limit": (429, True),
    "moderation": (451, False),
    "network": (503, True),
    "server": (503, True),
    "configuration": (503, False),
    "timeout": (504, True),
    "malformed": (500, False),    # semantic failure: degrade this call
    "schema": (500, False),
    "input": (422, False),        # state unusable — never a provider call
    "provider_error": (500, False),  # unknown: fail safe
}

# Default retry budgets. Live estimation allows a configured retry count only
# for transient failures; persistent infrastructure failures pause the run.
RETRY_BUDGET = {
    "network": 1, "server": 1, "auth": 0, "quota": 0, "rate_limit": 1, "timeout": 1,
    "moderation": 0, "malformed": 0, "schema": 0, "input": 0,
    "provider_error": 0, "configuration": 0,
}

# Ordered: first match wins. Whole-stderr search, case-insensitive.
_SIGNATURES = (
    ("configuration", re.compile(r"invalid (output )?schema|unsupported.*schema|schema.*not supported", re.I)),
    ("auth", re.compile(
        r"401 Unauthorized|invalid_api_key|invalid api key|unauthori[sz]ed|"
        r"authentication (failed|error|required)|not logged in|login required",
        re.I)),
    ("quota", re.compile(
        r"insufficient_quota|exceeded your current quota|usage[ _]limit|"
        r"out of credits|credit balance|billing (hard )?limit|quota exceeded|"
        r"plan limit",
        re.I)),
    ("rate_limit", re.compile(
        r"\b429\b|rate[ _-]?limit|too many requests|slow down", re.I)),
    ("server", re.compile(r"\b50[0234]\b|internal server error|service unavailable|bad gateway", re.I)),
    ("moderation", re.compile(
        r"content_policy|content policy|moderation|flagged by|"
        r"usage policies|safety system|refus(ed|al) to (comply|answer)",
        re.I)),
    ("network", re.compile(
        r"Reconnecting\.\.\.\s*\d+/\d+|stream disconnected before completion|"
        r"connection refused|could not resolve|name resolution|"
        r"network is unreachable|dns error|error sending request|"
        r"connection reset|failed to connect|tls handshake|"
        r"connection timed out|timed out connecting",
        re.I)),
)


class ProviderError(Exception):
    """Structured provider failure. `error_class` is the retry/report key."""

    def __init__(self, error_class, detail, code=None, retryable=None,
                 attempt_output=None):
        if error_class not in ERROR_CLASSES:
            error_class = "provider_error"
        default_code, default_retry = ERROR_CLASSES[error_class]
        self.error_class = error_class
        self.code = default_code if code is None else code
        self.retryable = default_retry if retryable is None else retryable
        self.detail = (detail or "")[:2000]
        self.attempt_output = attempt_output
        super().__init__(f"{error_class}: {self.detail[:200]}")

    def as_doc(self):
        return {"class": self.error_class, "code": self.code,
                "retryable": self.retryable, "detail": self.detail}


def status_for(error_class):
    """W-5 response status implied by a terminal error class."""
    if error_class == "timeout":
        return 504
    if error_class == "input":
        return 422
    if error_class in ("malformed", "schema"):
        return 500
    # auth / quota / rate_limit / moderation / network / unknown provider
    # exit: the provider did not deliver — 503, never "responder reasoning".
    return 503


def classify(stderr, returncode=None, stdout=None):
    """Classify a failed provider invocation from the WHOLE stderr text."""
    text = stderr or ""
    tail = text[-1500:]
    for name, rx in _SIGNATURES:
        if rx.search(text):
            return ProviderError(name, f"exit {returncode}: {tail}",
                                 attempt_output=stdout)
    return ProviderError("provider_error",
                         f"unclassified provider failure exit {returncode}: {tail}",
                         attempt_output=stdout)


def budget_for(error_class, cap=None):
    """Retries allowed for this class, capped by LLMOSES_LIVE_RETRIES."""
    b = RETRY_BUDGET.get(error_class, 0)
    if cap is not None:
        b = min(b, max(0, int(cap)))
    return b


def _write_schema(td, output_schema):
    if output_schema is None:
        return None
    path = os.path.join(td, "output-schema.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(output_schema, fh)
    return path


def _run(cmd, prompt, timeout_s, cwd, env):
    try:
        # subprocess.run(input=...) closes stdin after writing, which the CLI
        # needs: with a prompt argument and stdin left open it prints
        # "Reading additional input from stdin..." and waits for EOF (§5).
        return subprocess.run(cmd, input=prompt, text=True, capture_output=True,
                              timeout=timeout_s, cwd=cwd, env=env, check=False)
    except subprocess.TimeoutExpired as e:
        raise ProviderError("timeout",
                            f"provider timeout after {timeout_s}s: {e}") from e
    except FileNotFoundError as e:
        raise ProviderError("provider_error", f"provider not found: {e}") from e


def invoke(prompt, model, effort, timeout_s, output_schema=None):
    """Run the provider once. Returns the answer text; raises ProviderError."""
    live_cmd = os.environ.get("LLMOSES_LIVE_CMD")
    with tempfile.TemporaryDirectory(prefix="llmoses-live-provider-") as td:
        schema_path = _write_schema(td, output_schema)
        env = dict(os.environ)
        if schema_path:
            env["LLMOSES_OUTPUT_SCHEMA_PATH"] = schema_path
        if live_cmd:
            cmd = shlex.split(live_cmd)
            if not cmd:
                raise ProviderError("provider_error", "LLMOSES_LIVE_CMD was empty")
            proc = _run(cmd, prompt, timeout_s, None, env)
            if proc.returncode != 0:
                raise classify(proc.stderr, proc.returncode, proc.stdout)
            return proc.stdout

        out_path = os.path.join(td, "last-message.txt")
        cmd = ["codex", "exec", "-m", model,
               "-c", f"model_reasoning_effort={effort}",
               "--sandbox", "read-only", "--skip-git-repo-check",
               "--output-last-message", out_path]
        if schema_path:
            cmd += ["--output-schema", schema_path]
        cmd.append("-")
        proc = _run(cmd, prompt, timeout_s, td, env)
        if proc.returncode != 0:
            raise classify(proc.stderr, proc.returncode, proc.stdout)
        try:
            with open(out_path, "r", encoding="utf-8") as fh:
                return fh.read()
        except OSError as e:
            raise ProviderError("malformed",
                                f"codex exec produced no last message: {e}") from e
