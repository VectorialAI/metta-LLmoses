# ============================================================================
# metta-moses on PeTTa — reproducible run/dev container
# ----------------------------------------------------------------------------
# Grounded in (verified against the actual repos, not assumed):
#   * metta-moses CI (.github/workflows/MeTTa-CI.yml): runs inside a prebuilt
#     PeTTa image and just executes `python3 scripts/run-tests.py`.
#   * metta-moses setup.sh: clones patham9/PeTTa @ a pinned commit, fixes
#     run.sh, puts the PeTTa dir on PATH. (It never touches Rust/MORK.)
#   * PeTTa's own CI Dockerfile (patham9/PeTTa/.github/ci/Dockerfile):
#         FROM swipl:latest
#         apt-get install build-essential python3-dev
#     i.e. the official SWI-Prolog image + Python embedding headers. Nothing else.
#   * trueagi-io/PeTTa README: deps are "SWI-Prolog >= 9.3.x" and
#     "Python 3.x (for janus Python interop)". MORK/FAISS are OPTIONAL
#     (only needed for MORK/FAISS-backed atom spaces, which metta-moses
#     does not use — a grep of the repo finds zero `mork` references outside
#     setup.sh's path-rewrite lines).
#   * SWI-Prolog docs: library(janus) (Prolog->Python) is bundled in the PPA
#     and in the official Docker images; building it needs python3-dev.
#
# WHY base on `swipl` instead of a from-absolute-scratch SWI-Prolog build:
#   PeTTa hard-requires library(janus). The official `swipl` image already
#   bundles a janus-capable SWI-Prolog (>=9.3.x). Rebuilding swipl+janus from
#   source would add a large, fragile build for zero functional gain. This is
#   the same base the PeTTa maintainers use in their own CI.
# ============================================================================

# SWI-Prolog official image tag — pinned to a concrete digest-stable tag so a
# future `stable` or `latest` bump cannot silently shift Prolog/janus behaviour.
# All 10.x images bundle janus and are multi-arch (amd64 + arm64).
# To bump: verify the new tag at hub.docker.com/_/swipl/tags, check the
# SWI-Prolog changelog for any janus API changes, then update this value
# deliberately and re-run the full test suite.
ARG SWIPL_TAG=10.0.2
FROM swipl:${SWIPL_TAG}

# PeTTa commit pinned by metta-moses/setup.sh. Keep it pinned so the wiring
# (run.sh shape, src/main.pl interface) matches what metta-moses expects.
# PeTTa runtime source.
#
# IMPORTANT — this differs from metta-moses/setup.sh on purpose:
#   setup.sh clones patham9/PeTTa @ c04c012 (HEAD of that repo, dated
#   2025-11-19). That repo is a STALE personal fork: its newest commit predates
#   builtins that current metta-moses code depends on. Concretely, metta-moses
#   modules (utilities/general-helpers, feature-selection/*, representation/lsk,
#   representation/representation, optimization/pge) call `(first ...)`, whose
#   own definition is commented out in general-helpers.metta because the code
#   now expects PeTTa to provide it. `first` (and `last`, `is-alpha-member`) are
#   registered builtins ONLY in trueagi-io/PeTTa (the repo metta-moses's README
#   actually links to) — not in patham9 @ c04c012. Using the stale pin makes
#   every test that exercises a `first`-dependent path fail with a Prolog
#   `is/2: Type error: character expected, found 'first'`.
#
# So we use the maintained upstream, pinned for reproducibility. trueagi's
# run.sh self-locates (SCRIPT_DIR=$(dirname $0)), so no path rewriting needed.
#
# BUMPING PETTA_COMMIT: trueagi-io/PeTTa HEAD keeps moving. Staying on
# ebdb511 is the safe default. Before bumping, review the commit log for
# breaking changes to builtins or run.sh's interface, then re-run the full
# test suite (python3 scripts/run-tests.py) to confirm nothing regresses.
ARG PETTA_REPO=https://github.com/trueagi-io/PeTTa
ARG PETTA_COMMIT=ebdb51168135f7fdf68c59acf7521a1b85c19ba0

# UTF-8 locale: without this, SWI-Prolog emits "Illegal multibyte Sequence"
# on the emoji (✅/❌) and other UTF-8 in the .metta files.
# PYTHONPATH: makes utilities/ importable by bare module name from any CWD.
# The embedded CPython (janus) inherits the process environment, so
# `!(import! &self "llmoses_emitter.py")` resolves without a brittle
# ../../ prefix regardless of which .metta entry point is running.
ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/workspace/metta-moses/utilities:/workspace/metta-moses/llmoses/utilities

# Build + Python embedding deps (matches PeTTa's own CI Dockerfile), plus git.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        build-essential \
        python3 \
        python3-dev \
        git \
        ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# ----------------------------------------------------------------------------
# Install PeTTa (the MeTTa-in-Prolog runtime).
# trueagi's run.sh already resolves its own location and falls back to the
# pure-Prolog path when libmork_ffi.so is absent, so unlike setup.sh we need no
# path surgery. We only ensure a shebang + exec bit, because scripts/run-tests.py
# executes run.sh directly (not via `sh`), which needs an interpreter line.
# We deliberately DO NOT run PeTTa's build.sh (Rust/MORK/FAISS) — unused here.
# ----------------------------------------------------------------------------
ENV PETTA_DIR=/opt/PeTTa
RUN git clone "${PETTA_REPO}" "${PETTA_DIR}" \
 && cd "${PETTA_DIR}" \
 && git checkout "${PETTA_COMMIT}" \
 && if ! head -1 run.sh | grep -q '^#!'; then sed -i '1i#!/bin/sh' run.sh; fi \
 && chmod +x run.sh

# Put run.sh on PATH so `shutil.which("run.sh")` in scripts/run-tests.py finds it.
ENV PATH="${PETTA_DIR}:${PATH}"

# ----------------------------------------------------------------------------
# metta-moses source. COPY (not clone) so your local working tree — including
# in-progress LLMOSES changes — is what runs. For live editing, bind-mount over
# this at run time (see the run commands in BUILD_AND_RUN.md).
# ----------------------------------------------------------------------------
WORKDIR /workspace/metta-moses
COPY . /workspace/metta-moses

# Declare the bind-mount point for host-persisted outputs and wrapper logs.
# At run time the Makefile mounts <repo>/outputs → this path, so anything the
# wrapper writes under llmoses/outputs/ is visible on the host
# even after the container exits.  Creating the sub-directories here ensures
# they exist if no bind-mount is provided (e.g. a bare `docker run`).
RUN mkdir -p /workspace/metta-moses/llmoses/outputs/logs \
          && mkdir -p /workspace/metta-moses/llmoses/outputs/states

#Saving myself some typing
RUN chmod +x run_moses_demo.sh
RUN chmod +x run_strategy_state_test.sh
RUN chmod +x run_regression_state_test.sh

# Default: run the full metta-moses test suite exactly as CI does.
# Override with e.g.:  docker run --rm IMAGE run.sh deme/tests/expand-demes-test.metta
CMD ["python3", "scripts/run-tests.py"]