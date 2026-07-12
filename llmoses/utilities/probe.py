"""Phase II throwaway probe: does a seconds-long blocking py-call survive a
PeTTa mid-reduction, and does the returned 0 resp-binding reduce cleanly?

Not imported by any production module. Delete once the foothold is proven.
"""
import time


def block_n(n):
    """Sleep n seconds on the calling (Prolog query) thread, then return 0 —
    shape-identical to the real await_response v0 contract."""
    time.sleep(float(n))
    return 0
