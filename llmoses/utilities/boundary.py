"""Pure value-unwrap helpers for the MeTTa -> Python (py-call) boundary.

Values arrive as native Python numbers, strings, nested lists (preOrder ASTs),
Cons spines, or shallow wrapped atoms like ['mkMultip', 3].
"""

_ABSENT_ATOMS = {"", "None", "()", "Nil"}
def _flat(x):
    try:
        return str(x).strip()
    except Exception:
        return "<unrepr>"


def _num(x):
    if isinstance(x, bool):
        return x
    if isinstance(x, (int, float)):
        return x
    try:
        return int(str(x).strip())
    except (TypeError, ValueError):
        try:
            return float(str(x).strip())
        except (TypeError, ValueError):
            return _flat(x)


def unwrap_atom(x):
    """['mkMultip', 3] -> 3 ; ['mkDemeId', '1'] -> '1' ; 
    only unwraps the shallow [name, payload] atom shape"""
    if isinstance(x, list) and len(x) == 2 and isinstance(x[0], str):
        return x[1]
    return x


def cons_to_list(x):
    """Read a PeTTa flat list or an explicit Cons/cons spine.
       ['mkBScore', [-1, 0]] -> [-1, 0] (native PeTTa bridge)
       ['Cons', 1.0, ['Cons', 0.0, 'Nil']] -> [1.0, 0.0]
       'Nil' -> []
    Unwrap mkBScore specifically: a two-label list is already a flat list."""
    if isinstance(x, (list, tuple)) and len(x) == 2 and x[0] == "mkBScore":
        x = x[1]
    if not isinstance(x, (list, tuple)):
        return []
    if not x or x[0] not in ("Cons", "cons"):
        return list(x)
    out = []
    cur = x
    while isinstance(cur, (list, tuple)) and len(cur) == 3 and cur[0] in ("Cons", "cons"):
        out.append(cur[1])
        cur = cur[2]
    return out


def expr_to_str(x):
    """Render a marshalled preOrder expression (nested list) to an s-expression
    string for stable hashing/display. Scalars pass through as str."""
    if isinstance(x, list):
        if not x:
            return "()"
        return "(" + " ".join(expr_to_str(e) for e in x) + ")"
    return str(x)


def demeid(x):
    """mkDemeId payload: dotted pair ($nExpansion . $idx) -> 'exp.idx'; bare
    numeric string (nDeme<=1) passes through; anything else -> _flat."""
    # mkDemeId payload (createDemeIds -> mkDemeId, deme/deme-id-creation.metta),
    # two marshalled forms:
    #   dotted pair ($nExpansion . $idx) -> ['<exp>', '.', '<idx>']  (nDeme > 1)
    #   bare numeric string                                          (nDeme <= 1)
    payload = unwrap_atom(x)
    is_dotted_pair = (isinstance(payload, list) and len(payload) == 3
                      and str(payload[1]).strip() == ".")
    if is_dotted_pair:
        return f"{_flat(payload[0])}.{_flat(payload[2])}"
    return _flat(payload)


def cr_or_none(x):
    """Coerce the complexity_ratio run param to a number, or None when absent."""
    return _num(x) if x is not None else None


def present_atom(x):
    """Flat string, or None when the value is an absent-style sentinel."""
    s = _flat(x)
    return None if s in _ABSENT_ATOMS else s
