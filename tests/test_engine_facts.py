"""Every value domain in engine_facts.json is what the installed engine does.

For each key: a value outside the listed domain must be refused, and a value inside it
must not be refused for that key (a refusal for some other reason is fine: ntb=2 without
ntp, say). Skipped unless the engine is installed.
"""
import json
from pathlib import Path

import pytest

from cases import mdin
from mdin_check import engine

FACTS = json.loads((Path(__file__).resolve().parent.parent / "mdin_check" / "data" / "engine_facts.json").read_text())
SYS = Path(__file__).parent / "systems"

# settings that make a value of the key legal on its own, so a refusal points at the key
CONTEXT = {"ntt": ({}, ("gamma_ln",)), "imin": ({"maxcyc": 1}, ()), "ntmin": ({"imin": 1, "maxcyc": 1}, ()),
           "igb": ({"ntb": 0, "cut": 999.0}, ()), "ntb": ({}, ()), "irest": ({"ntx": 5}, ())}


def params():
    out = []
    for eng in ("pmemd", "sander"):
        for key, allowed in FACTS[eng]["domains"].items():
            lo, hi = min(allowed), max(allowed)
            outside = [v for v in range(lo - 2, hi + 3) if v not in allowed]
            out += [(eng, key, v, False) for v in outside] + [(eng, key, v, True) for v in allowed]
    return out


P = params()


@pytest.mark.parametrize("eng,key,value,inside", P, ids=[f"{e}-{k}={v}" for e, k, v, _ in P])
def test_domain(eng, key, value, inside):
    if not engine.find(eng):
        pytest.skip(f"{eng} not installed")
    over, drop = CONTEXT.get(key, ({}, ()))
    if key == "ntb" and value == 2:
        over = {"ntp": 1}
    if key == "ntt" and value in (9, 10):
        over, drop = {"ntc": 1, "ntf": 1, "dt": 0.001}, ()
    if key == "ntp" and value > 0:
        over = {"ntb": 2, **({"csurften": 1.0} if value == 3 else {})}
    text = mdin({**over, key: value}, drop=drop)
    crd = "solv_vel.rst7" if key in ("irest", "ntx") else "solv.rst7"
    r = engine.run(text, SYS / "solv.parm7", SYS / crd, engine=eng)
    assert not r.timed_out, "the engine timed out: no verdict"
    if inside:
        assert r.accepted or key not in r.error.lower(), f"{key}={value} refused: {r.error}"
    else:
        assert not r.accepted, f"{key}={value} is outside the listed domain but {eng} accepted it"


SIGN = [(eng, key, -1) for eng in ("pmemd", "sander") for key in FACTS[eng]["nonnegative"]] + \
       [(eng, key, -1.0) for eng in ("pmemd", "sander") for key in FACTS[eng]["positive"]]


@pytest.mark.parametrize("eng,key,value", SIGN, ids=[f"{e}-{k}={v}" for e, k, v in SIGN])
def test_sign(eng, key, value):
    if not engine.find(eng):
        pytest.skip(f"{eng} not installed")
    r = engine.run(mdin({key: value}), SYS / "solv.parm7", SYS / "solv.rst7", engine=eng)
    assert not r.timed_out, "the engine timed out: no verdict"
    assert not r.accepted, f"{key}={value} listed as invalid but {eng} accepted it"
