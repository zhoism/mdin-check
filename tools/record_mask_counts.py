"""Record pmemd's atom count for a corpus of masks on the test systems.

    python tools/record_mask_counts.py [--n 400]

Writes tests/data/mask_counts.json: for each system, mask -> count, or "REJECT: <error>".
tests/test_mask.py replays it against mdin_check.mask without needing pmemd. The corpus is
the hand-written cases below plus a seeded random sample from a small mask grammar.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from pmemd_mask import count  # noqa: E402

SYSTEMS = {"solv": ("solv.parm7", "solv.rst7", True), "vac": ("vac.parm7", "vac.rst7", False)}

HAND = [
    ":1-3", "(:1-3)@CA", "(:1-3)&@CA", ":1-3@CA", "(:1-3):ALA", ":1,ALA", ":ALA", "@CA", "@H", "@H=", ":WAT", ":wat",
    ":HOH", ":Na+", ":NA+", ":Cl-", "@1-5,CA", "@1-5", "@%H", "@%h", ":1-3 | :5", ":1-3|:5&@CA", "!:WAT", "!:WAT&!@H=",
    ":1<:3.0", ":1<@3.0", ":1>:3.0", ":1<:3.0&!:WAT", ":*", "@*", "*", ":9999", ":10-1", ":A=", ":AL=", "@C=",
    ":1-3@C=", "@CA,C,N,O", ":1-10@CA,C,N,O", "@/H", "^1", "::A", ":1:3", ":1-3@CA.C", "@H*", ":1-3&(@CA|@N)",
    "(:1-3|:5)&@CA", ":1-3@%CX", "@%CX,H", " :1 ", ":1 - 3", "!(:1-3)", "!!:1", ":1&:2", ":1-3<@2.0", "(:1)<:5.0",
    ":1<:5.0", ":1-10>@20.0", "@EPW", ":WAT@O", ":WAT@EPW", "(:2)(:3)", ":2(:3)", "@CA(:3)", "(:1-3)!@CA", ":1-3!@CA",
    ":1@CA<@3.0", ":1-3@CA<:2.0", ":1<3.0", "@CA&:1-3<@3.0", "(@CA&:1-3)<@3.0", "!:1<@3.0", ":1-3&", "&:1", "|:1",
    ":1|", "()", "(:1", ":1)", ":", "@", ":,1", ":1,", ":1-", ":-1", ":1--3", ":0", ":0-3", "@0", "@6104", "@6105",
    "@6100-6110", ":1500-1501", ":1501-1600", ":1,3-5,7", ":ALA,HIE", ":ALA,HI=", ":A=,H=", "@CA,1", "@%", ":1@",
    ":1@%", ":1@%CX", ":1:2", ":1&@CA|@N", "@N&:1|:2", ":1<:1e1", ":1<:10", ":1-2<:3.0|:5", "!@H=&:1-10",
    ":1-10&!@H=", "@CA|@CB", ":TRP@C=", ":TRP@%CA", "(:1-5|:7)&!(@H=|@EPW)", ":1-10@N,CA,C,O", "!:WAT,Na+,Cl-",
    "!(:WAT|:Na+|:Cl-)", ":11-15", "@%OW", "@%EP", ":WAT&@O", ":Na+|:Cl-", "(:1-10)<:6.0&:WAT", ":Cl-<:5.0",
    ":1-10@H=&!@H", "@HA,HA2,HA3", ":GLY", ":HIS", ":HI=", ":CY=", ":CYX", ":NALA", ":CALA",
    "@CA@N", "@CA:1", ":1-3^2", "@C?", "@C/", ":1.5", ":1-3@CA,N.", "<:3.0", ":1<", ":1<:abc", ":1>@", "#1", ":1%",
    "@%CX@N", "%CX", ":1-3@%CX,%HC", ":1-TOTRES", ":A-B", ":1-ALA", ":ALA-", ":LIGAND1", ":ABCDE", ":ABCD", "@ATOMS",
    "@ABCDE", "@ABCD", ":WAT@ABCDEF", ":WATER", ":WAT,ABCDE", ":ABCD=", ":ABCDE=", "@HA2=", "@%ABCDE", "@%ABCD",
    "!!:1", "(!!:1)", ":2|!!:1", "!(!:1)", "!!!:1", ":2&!!!:1", "@%C=", "@%H=", ":1@%C=", "@%*",
    ":105<:4.0", ":105<@5.0", ":600<:4.0", ":833>:6.0",
]


def generated(n: int, seed: int = 7) -> list[str]:
    rnd = random.Random(seed)
    res_names = ["ALA", "HIE", "CYS", "ASP", "LYS", "GLU", "TRP", "PHE", "SER", "WAT", "Na+", "Cl-", "HI=", "A=", "G="]
    atom_names = ["CA", "C", "N", "O", "H", "H=", "C=", "O=", "N=", "HA", "CB", "SG", "EPW", "H1", "OXT", "Na+"]
    types = ["CX", "H", "HC", "OW", "C", "N", "O", "EP", "C="]

    def numlist(hi):
        parts = []
        for _ in range(rnd.randint(1, 3)):
            a = rnd.randint(1, hi)
            parts.append(f"{a}-{rnd.randint(a, hi)}" if rnd.random() < 0.5 else str(a))
        return ",".join(parts)

    def elem():
        k = rnd.random()
        if k < 0.3:
            return ":" + (numlist(12) if rnd.random() < 0.6 else ",".join(rnd.sample(res_names, rnd.randint(1, 2))))
        if k < 0.55:
            return "@" + (numlist(160) if rnd.random() < 0.3 else ",".join(rnd.sample(atom_names, rnd.randint(1, 3))))
        if k < 0.65:
            return "@%" + ",".join(rnd.sample(types, rnd.randint(1, 2)))
        r = ":" + numlist(10)
        return r + ("@%" + rnd.choice(types) if rnd.random() < 0.2 else "@" + ",".join(rnd.sample(atom_names, rnd.randint(1, 2))))

    def expr(d):
        k = rnd.random()
        if d > 2 or k < 0.35:
            e = elem()
        elif k < 0.5:
            e = "!" + expr(d + 1)
        elif k < 0.6:
            e = "(" + expr(d + 1) + ")"
        else:
            e = expr(d + 1) + rnd.choice(["&", "|"]) + expr(d + 1)
        if rnd.random() < 0.08:
            e = "(" + e + ")" + rnd.choice(["<:", "<@", ">:", ">@"]) + str(rnd.choice([2.0, 3.5, 5.0]))
        return e

    out = []
    while len(out) < n:
        m = expr(0)
        if m not in out:
            out.append(m)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=400)
    a = ap.parse_args()
    masks = HAND + generated(a.n)
    out = {}
    for name, (top, crd, periodic) in SYSTEMS.items():
        d = ROOT / "tests" / "systems"
        with ThreadPoolExecutor(10) as ex:
            res = list(ex.map(lambda m: count(str(d / top), str(d / crd), m, periodic=periodic), masks))
        out[name] = {m: (n if n is not None else f"REJECT: {err}") for m, (n, err) in zip(masks, res)}
        print(name, sum(isinstance(v, int) for v in out[name].values()), "counted,",
              sum(isinstance(v, str) for v in out[name].values()), "rejected")
    (ROOT / "tests" / "data" / "mask_counts.json").write_text(json.dumps(out, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
