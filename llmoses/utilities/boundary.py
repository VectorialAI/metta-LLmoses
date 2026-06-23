"""Pure value-unwrap helpers for the MeTTa -> Python (py-call) boundary.

Values arrive as native Python numbers, strings, nested lists (preOrder ASTs),
Cons spines, or shallow wrapped atoms like ['mkMultip', 3]. Everything here is a
pure function of its argument with no module state, so it is safe to share across
the builder, the atom-evidence walker, and any future emitter.
"""

_ABSENT_ATOMS = {"", "None", "()", "Nil"}
def _flat(x):
    """Best-effort string coercion; never raises."""
    try:
        return str(x).strip()
    except Exception:
        return "<unrepr>"


def _num(x):
    """Best-effort numeric coercion; falls back to a flat string. Never raises."""
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
    """['mkMultip', 3] -> 3 ; ['mkDemeId', '1'] -> '1' ; bare value -> unchanged.
    Only unwraps the shallow [name, payload] atom shape; leaves anything else."""
    if isinstance(x, list) and len(x) == 2 and isinstance(x[0], str):
        return x[1]
    return x


def cons_to_list(x):
    """Flatten a Cons spine to a flat Python list.
       ['Cons', 1.0, ['Cons', 0.0, 'Nil']] -> [1.0, 0.0]
       'Nil' -> []
    Also accepts a wrapped list atom like ['mkBScore', <spine>] and unwraps first."""
    if isinstance(x, list) and len(x) == 2 and isinstance(x[0], str) and x[0] != "Cons":
        x = x[1]
    out = []
    cur = x
    while isinstance(cur, list) and len(cur) == 3 and cur[0] == "Cons":
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
    """Coerce complexity_ratio to float/int or None.
    The boolean context emits () (marshalled as '()' or [] or empty string);
    treat any of those as absent -> JSON null. Real numeric values pass through _num.

    NOTE: this defensive coercion is the prime candidate for collapse. It stays
    until a boundary probe confirms what complexity_ratio actually marshals to
    (always-float vs float-or-absent). See marshal_probe notes."""
    if x is None:
        return None
    s = str(x).strip()
    if s in ("", "()", "Nil"):
        return None
    if isinstance(x, list) and len(x) == 0:
        return None
    return _num(x)


def present_atom(x):
    """Flat string, or None when the value is an absent-style sentinel."""
    s = _flat(x)
    return None if s in _ABSENT_ATOMS else s

