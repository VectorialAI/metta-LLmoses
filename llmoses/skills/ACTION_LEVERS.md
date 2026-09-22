# Four levers

P8: mutate the native prior P, never replace it with an absolute distribution.
Every site constructs anchored A, mixes D0=(1-b)P+bA, then sharpens
D=normalize(D0^(1/T)). At b=0 sharpening is bypassed. Identity guidance with
T=1 preserves P; a nonunit commanded temperature is itself an adjustment.

| Call | Lever | Legal adjustment | Native prior |
|---|---|---|---|
| 1 | 4, rowweight | Per-row multiplier, identity 1, clamp [0,W] | Unit row weights |
| 2 | 1, exemplar | Per-member score offset, identity 0, clamp ±delta_max | Native score roulette |
| 3 | 5, atom | Ordered-pair factors in a causal conditional policy | Uniform pair pool at each site |
| 4 | 2, retention | Per-member score offset, identity 0, clamp ±delta_max | softmax(penalized score/tau) |

Row weights are normalized to mean one and installed in shared cscore arithmetic.
The full archive is rescored from cached behavioural vectors before Call 2; this
arithmetic does not count as fitness evaluations. Unweighted scores are emitted.

For calls 2 and 4, A=softmax((penScore+offset)/T_native). T_native is selection
 temperature/100 at Call 2 and tau at Call 4. An omitted member has offset zero.
An offset of 1 is one truth-table row of score credit. It is not a probability.

Retention constructs the complete admitted/deduplicated candidate union before
one draw, without a scalar eligibility band. Native deme trimming and dominance
remain. K is deterministic, clamped to a floor and feasible ceiling. If the
floor is impossible, the ceiling wins and floor_shortfall is logged. A power
adjustment (or configured clamp redistribution) creates inclusion probabilities
summing to K. Randomized-order Madow sampling chooses exactly K distinct members.
The retention baseline itself differs from upstream even with b=0.

## Conditional pair policy

A policy has `base` factors and conditional `rules`. Every matching rule
multiplies its factors with the base. Omitted factors are 1; finite factors are
clamped to [0,W]. Zero total mass falls back to P and is logged. Ordered pairs
must name distinct alphabet atoms; a pair need not appear at a concrete site.
Feature selection can make a valid pair unreachable in a particular build.

A rule is `{when: {...}, adjust: [{pair: ["X1","X2"], weight: 2}]}`.
Conditions are conjunctions:

- `op`: AND or OR at the draw.
- `depth`: nonnegative integer min and/or max of this node's current depth.
- `site_kind`: exemplar_node, appended_child, literal_wrap, sampled_subtree.
- `local_literals`: required `{atom, polarity}` entries, polarity + or -, among current children.
- `ancestor_drew`: one ordered pair already drawn at a strict ancestor.
- `already_drawn`: one ordered pair committed anywhere earlier in this build.

No final depth, descendants, knob state, or paths may be predicates.
`context_radius=0` permits base only; 1 permits local conditions; 2 adds
ancestor_drew; 3 adds already_drawn. `rule_budget` bounds the rule count.
These capacity controls are independent of b. Empty policy is identity.

Call 3 occurs after selection and before representation construction. The
harness owns history and site sequencing. Sampled clauses can create later
sites; only already committed information can match a rule. Logging identifies
sites by sequence, never by native paths. Hill climbing determines which
proposed pair knobs become active; a draw is not an active candidate feature.
