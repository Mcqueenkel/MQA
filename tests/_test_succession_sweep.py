# Check the start-102 succession-point sweep candidate order.
# Run with: python tests/_test_succession_sweep.py
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root, for `import main`

import main


def run():
    gen = main._succession_sweep_candidates

    # The live failure: parent estimate 335, account only holds 53. The OLD sweep (est +/-20 = 315..355)
    # could never reach 53. The fix must probe the held value + 0 right after the estimate.
    c = gen(335, 53)
    assert c[:3] == [335, 53, 0], c[:3]          # estimate first, then held, then 0 -> friend resolves fast
    assert 53 in c and 0 in c
    assert all(v >= 0 for v in c), "no negative succession points"
    assert len(c) == len(set(c)), "candidates must be de-duplicated"

    # held==est==0 degenerates cleanly (no dupes, still non-empty, 0 present)
    z = gen(0, 0)
    assert z[0] == 0 and len(z) == len(set(z)) and all(v >= 0 for v in z)

    # estimate near 0 must not emit negatives
    n = gen(3, 1)
    assert all(v >= 0 for v in n) and n[0] == 3

    print("PASS _succession_sweep_candidates: estimate->held->0 order, no negatives, deduped")


if __name__ == "__main__":
    run()
