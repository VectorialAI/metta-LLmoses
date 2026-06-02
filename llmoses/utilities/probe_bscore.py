"""Throwaway marshalling / rendering probe.
Prints the Python type and repr of whatever MeTTaLog hands across py-call.
Lives in llmoses/utilities/ so it is importable by bare module name
(PYTHONPATH includes this directory).
"""

def show(label, x):
    print(f"PROBE {label}: type={type(x).__name__} repr={x!r}")
    return 0

def show_many(label, *args):
    print(f"PROBE {label}: nargs={len(args)}")
    for i, a in enumerate(args):
        print(f"  arg[{i}]: type={type(a).__name__} repr={a!r}")
    return 0
