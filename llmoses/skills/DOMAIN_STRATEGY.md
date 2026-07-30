# Strategy Domain

Strategy runs search game or policy program trees. The problem spec usually includes available moves, number of games, opponent policy, and complexity ratio.

Interpretation notes:

- Strategy cooccurrence should be read as move or policy structure evidence, not boolean literal evidence.
- A candidate with moderate immediate score may still be useful if it represents a distinct strategic pattern.
- Deme neighborhood sizes and instance counts help estimate whether a strategy region has been searched deeply or only sampled lightly.
- Complexity can be useful when it encodes conditional play, but unproductive branching should be penalized.

Prefer strategies that improve score, represent distinct behavior, and are not merely larger versions of weak policies.
