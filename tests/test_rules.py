"""mdin-check reports each case's codes, with the right severity, on the case's system."""
from pathlib import Path

import pytest

from cases import CASES
from mdin_check import rules
from mdin_check.topology import read_coordinates, read_prmtop

SYS = Path(__file__).parent / "systems"
_TOP = {}


def system(name, crd):
    if (name, crd) not in _TOP:
        top = read_prmtop(SYS / f"{name}.parm7")
        _TOP[(name, crd)] = (top, read_coordinates(SYS / crd, top.natom))
    return _TOP[(name, crd)]


PARAMS = [(c, e) for c in CASES for e in c.engines]


@pytest.mark.parametrize("case,eng", PARAMS, ids=[f"{c.name}[{e}]" for c, e in PARAMS])
def test_codes(case, eng):
    top, crd = system(case.system, case.crd)
    rep = rules.check_text(case.text, eng, top, crd)
    got = {f.code: f.severity for f in rep.findings}
    for code in case.codes:
        assert code in got, f"{code} missing; got {got}"
        if code in case.severity:
            assert got[code] == case.severity[code], f"{code} is {got[code]}, want {case.severity[code]}"
    if case.group_atoms is not None:
        assert [m["atoms"] for m in rep.masks if m["key"].startswith("group")] == case.group_atoms
    has_error = any(f.severity == "error" for f in rep.findings)
    assert has_error == (case.engine_verdict == "reject"), \
        f"engine {case.engine_verdict}s this file, mdin-check says {rep.verdict}: {got}"


def test_without_topology_still_checks_text():
    rep = rules.check_text("t\n&cntrl\n imin=0, ntsx=1, ntb=1, cut=9.0,\n/\n", "pmemd")
    assert rep.verdict == "reject"
    assert not rep.masks
