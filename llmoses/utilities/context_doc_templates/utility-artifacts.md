# Call-specific responses

Artifacts use `utilities/run-N/step-G-call-C.json`. Required envelope:

```json
{"run_seq":1,"generation":1,"call":2,"pass":false,"status":200,
 "outcome":{},"exemplar_utilities":[{"program_id":"p-offered-id","offset":0.5}]}
```

Only one call's guidance field is legal:

| Call | Field | Entry |
|---|---|---|
| 1 | row_weights | row (integer), weight |
| 2 | exemplar_utilities | program_id, offset |
| 3 | policy | base and rules, as below |
| 4 | retention_utilities | program_id, offset |

```json
{"base":[{"pair":["X1","X3"],"weight":1.4}],
 "rules":[{"when":{"op":"OR","depth":{"min":1},"site_kind":"sampled_subtree"},
           "adjust":[{"pair":["X2","X1"],"weight":0.5}]}]}
```

An optional temperature is legal only if commandable for this call:
T_rowweight, T_exemplar, T_atom, T_retention. Ingest clamps it to configured bounds.
All numbers must be finite; booleans are not numeric values. Row IDs and member
IDs must be offered in this call. Pair labels need only belong to the alphabet.
Duplicate entries are rejected. Valid row/member entries survive invalid peers;
an invalid policy rejects the policy as a whole. Unknown fields, wrong call
content, and fence mismatches reject the entire response.

A neutral reply carries pass=true and no guidance. Status 204 means intentional
abstention; 422 means unusable input; 500 means semantic response failure.
Statuses 503/504 mean infrastructure failure and cause checkpointed pause.
Status 200 requires pass=false. Envelope metadata is validated on every status,
including declines. A semantic failure degrades only this call, not later calls.

`outcome` can contain attempts (positive integer), retried (boolean), salvage
(requested/survived nonnegative integers), coverage (mode full/sparse,
requested/supplied integers), error_class/detail/protocol_version (strings),
and context (strategy, chars, optional measured tokens, compressed, dropped).
Absent token counts mean unavailable; do not fabricate token measurements.

Prefer the slot interface: `row:0` and `member:ID` have numeric values;
`policy` has a structured object. Commandable temperatures have named numeric
slots. `assemble` supplies the fence and envelope. Rationale belongs in traces.
Comparator, complexity-ratio, mask-mode, global-prior, synergy, and contextual-axis
fields are retired and rejected, including on a decline.
