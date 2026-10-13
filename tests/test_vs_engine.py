"""Each case's recorded engine verdict still holds for the installed engine.

Skipped unless the engine is found (MDIN_CHECK_PMEMD / MDIN_CHECK_SANDER, AMBERHOME, or PATH).
This is what makes every "error" in mdin-check a claim about the engine, not about the manual.
"""
from pathlib import Path

import pytest

from cases import CASES
from mdin_check import engine

SYS = Path(__file__).parent / "systems"
PARAMS = [(c, e) for c in CASES for e in c.engines]


@pytest.mark.parametrize("case,eng", PARAMS, ids=[f"{c.name}[{e}]" for c, e in PARAMS])
def test_engine_verdict(case, eng):
    if not engine.find(eng):
        pytest.skip(f"{eng} not installed")
    r = engine.run(case.text, SYS / f"{case.system}.parm7", SYS / case.crd, engine=eng)
    assert not r.timed_out, "the engine timed out: no verdict"
    got = "accept" if r.accepted else "reject"
    assert got == case.engine_verdict, f"{eng} {got}s it ({r.error})"
