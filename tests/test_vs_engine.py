"""Each case's recorded engine verdict still holds for the installed engine.

Skipped unless the engine is found (MDIN_CHECK_PMEMD / MDIN_CHECK_SANDER, AMBERHOME, or PATH).
This is what makes every "error" in mdin-check a claim about the engine, not about the manual.
"""
import re
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


GROUPS = [(c, e) for c, e in PARAMS if c.group_atoms is not None]


@pytest.mark.parametrize("case,eng", GROUPS, ids=[f"{c.name}[{e}]" for c, e in GROUPS])
def test_group_atom_counts(case, eng):
    """mdin-check's count for each group is the engine's own."""
    from mdin_check import rules
    from mdin_check.topology import read_prmtop
    if not engine.find(eng):
        pytest.skip(f"{eng} not installed")
    r = engine.run(case.text, SYS / f"{case.system}.parm7", SYS / case.crd, engine=eng)
    printed = [int(n) for n in re.findall(r"Number of atoms in this group\s*=\s*(\d+)", r.log)]
    assert printed == case.group_atoms, f"{eng} printed {printed}"
    rep = rules.check_text(case.text, eng, read_prmtop(SYS / f"{case.system}.parm7"))
    assert [m["atoms"] for m in rep.masks if m["key"].startswith("group")] == case.group_atoms
