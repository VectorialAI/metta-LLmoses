# Run instructions

Run: `{run_id}`; current sequence: `{run_seq_text}`.
Problem: {problem_summary}
Active levers: {lever_text}

Use state/run-N/step-G-call-C.json, the matching action, and the canonical
llmoses/skills guides. Write utilities and traces before publishing response.
Call order: rows → exemplar → conditional pair policy → retention.
step-G.json is observational. CONTROL/pause requires repair and explicit resume.

Effective experiment parameters (operator record; not agent actions):
```json
{experiment_json}
```
