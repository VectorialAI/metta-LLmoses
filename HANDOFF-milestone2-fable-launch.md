# Launch prompt — M2 hardening implementation

Local working file, not for commit. Copy the block below as the opening
message for the new Fable session.

---

We are going to run a large scale job to push towards milestone 2 completion. I need you to be efficient but not necessarily conservative with tokens; this means you should think hard but avoid being wasteful and also make very liberal use of /codex-delegate. If codex runs out of tokens or if you are looping on the same problem with no progress, pause and check in with me before resuming.

**Scope.** Your job is to implement `PLAN-m2-hardening.md` (repo root) in full —
every `W-*` work item in its §6 table, in the dependency order it already
specifies. That document is the authoritative, current dev spec; nothing you
need is missing from it. Start your first action by opening it and beginning
implementation — don't spend a turn re-planning or re-deriving what it already
lays out.

**Documents to reference:**

- **`PLAN-m2-hardening.md`** (repo root) — the spec. Follow its own §6
  "Suggested order" and dependency table exactly. Its §8 (Verification) is
  your bar for done: the battery (50 assertions — TRANSPORT 9 + POLICY 41,
  already correct in the file), the failure-injection table (each check must
  reverse-check against pre-change code), and each item's own "Done criteria"
  line.
- **`HANDOFF-milestone2-followups.md`** (repo root) — background only. The
  hardening plan cites it a few times (§1.4, §7 decision 3, W-18) to explain
  *why* certain decisions were made. You do not need to and should not
  implement anything from it — its work items (a `replay` watcher mode, a
  λ-parameterized demo runner, submission-material generation) are a separate,
  later task, out of scope here.
- **`PROBE-codex-exec-streaming.md`** (repo root) — already-answered probe
  behind the plan's §5 and §9. Do not re-run it; its findings are already
  incorporated into the plan as settled fact.
- **Do not implement from `PLAN-m2-transport-hardening.md` or
  `PLAN-m2-failure-modes.md`** (repo root) — both are superseded, each carries
  an explicit header saying so, and are retained only for their derivations.
  `PLAN-m2-hardening.md` already incorporates what's still valid from them.
- **`llmoses/design-spec/v20_work.md`** — the canonical design spec, useful as
  read-only architecture reference (the hardening plan cites specific lines of
  it). Do not edit it.

**Explicit exclusions — do not do this work, it is out of scope for this job:**

- Do not implement anything from `HANDOFF-milestone2-followups.md` (replay
  mode, the λ-triple demo runner, verification/QA for either, the readme
  section, or any submission-material generation).
- Do not edit any documentation: not `llmoses/readme.md`, not
  `llmoses/design-spec/v20_work.md`, not `PLAN-m2-hardening.md` itself (don't
  mark items done in the file — track status via the code and tests, not via
  editing the plan), and don't author a new HANDOFF file.
- Do not run `git commit` at any point. Leave all changes in the working tree
  uncommitted for review — this is local development under direct supervision,
  nothing here needs to be committed by you.

**Done.** Every `W-*` item in the plan's §6 table is implemented and verified
per its own done criteria, the full battery is green, and the failure-injection
table passes with reverse-checks proven against pre-change code. If an item
turns out to be genuinely inapplicable or blocked, stop and say so rather than
skipping it silently or inventing a workaround.
