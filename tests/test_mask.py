"""The mask evaluator matches pmemd's own atom counts (recorded by tools/record_mask_counts.py)."""
import json
from pathlib import Path

import pytest

from mdin_check import mask
from mdin_check.topology import read_coordinates, read_prmtop

HERE = Path(__file__).parent
GOLD = json.loads((HERE / "data" / "mask_counts.json").read_text())


@pytest.mark.parametrize("system", sorted(GOLD))
def test_counts_match_pmemd(system):
    top = read_prmtop(HERE / "systems" / f"{system}.parm7")
    crd = read_coordinates(HERE / "systems" / f"{system}.rst7", top.natom)
    wrong = []
    for m, gold in GOLD[system].items():
        try:
            got = len(mask.select(m, top, crd))
        except mask.MaskError:
            got = "REJECT"
        except mask.Unsupported:
            continue
        want = "REJECT" if isinstance(gold, str) else gold
        # pmemd mis-evaluates '!!' where it does not reject it; mdin-check rejects it everywhere
        if got != want and not ("!!" in m and got == "REJECT"):
            wrong.append((m, want, got))
    assert not wrong, f"{len(wrong)} of {len(GOLD[system])} masks differ from pmemd: {wrong[:10]}"


def test_unsupported_is_rare():
    top = read_prmtop(HERE / "systems" / "solv.parm7")
    crd = read_coordinates(HERE / "systems" / "solv.rst7", top.natom)
    n = 0
    for m in GOLD["solv"]:
        try:
            mask.select(m, top, crd)
        except mask.Unsupported:
            n += 1
        except mask.MaskError:
            pass
    assert n <= len(GOLD["solv"]) // 20
