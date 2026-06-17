# MeTTa Primer

MeTTa values cross into Python through `py-call` and are decoded by `state_builder.py`.

Useful conventions:

- `Cons` and `Nil` represent list spines.
- `mkX` atoms are often shallow wrappers around payload values.
- Program trees are rendered as stable `tree_str` strings and hashed into `program_id`.
- `preOrder` expressions are used internally to keep AST structure available for extraction.
- Shadow files under `llmoses/` are imported instead of base MOSES files when hooks or fixes are needed.

For utility estimation, do not reason from raw MeTTa syntax unless the decoded JSON is insufficient. Prefer `program_id`, `tree_str`, score fields, and emitted state summaries.
