# State artifacts

Problem: {problem_summary}

# Four-call state

`state/run-N/run_config.json` is the effective experiment configuration and
problem specification. Every call state has integer run_seq, generation, call,
a metapopulation snapshot, cumulative evaluation count, previous_outcome, and
capture_status. Per-call artifacts are `step-G-call-C.json`; `step-G.json` is
an observational end-of-generation snapshot, never a request.

1. Generation top: full members and truth-table row slots, before row rescore.
2. After row rescore: current scored candidates and installed row weights.
3. After selection: selected exemplar, alphabet, static ordered-pair universe,
   enabled condition vocabulary, previous-generation draw history. No node list.
4. After construction, hill climbing and merge filtering: full candidate pool,
   draw records, per-deme knobs/counts, atom evidence, active-pair tags.

Members contain program_id, lossless tree_str, cscore, bscore, unweighted_score,
complexity, explored, lineage_depth/max_lineage_depth and active_pairs.
Active-pair tags carry build/site sequence, knob index, effective logical setting
and deme ID. Absent ancestor knobs suppress nested tags. These describe
representation activity before final tree reduction, not causal fitness credit.

`capture_status.ok=false` means incomplete capture, not deliberate omission.
Configured omitted sections use `gated: null`. Each draw has a distinct site_seq
and build_seq; harness-internal causal paths are provenance, not policy keys.
