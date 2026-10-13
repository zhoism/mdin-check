"""Ask an engine how many atoms a mask selects: its own "Mask ...; matches N atoms" line.

    python tools/pmemd_mask.py prmtop inpcrd "<mask>" ["<mask>" ...]

Each mask goes into restraintmask with ntr=1 and a 1-step minimization (no dynamics).
"""
from __future__ import annotations

import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mdin_check import engine  # noqa: E402

MATCHES = re.compile(r"Mask (.*); matches\s+(\d+) atoms")


def count(prmtop: str, inpcrd: str, mask: str, eng: str = "pmemd", periodic: bool = True) -> tuple[int | None, str]:
    """(atoms matched, "") or (None, the engine's error)."""
    q = "'" + mask.replace("'", "''") + "'"
    ntb = "ntb=1, cut=8.0," if periodic else "ntb=0, igb=0, cut=99.0,"
    text = f"mask probe\n&cntrl\n imin=1, maxcyc=1, ntpr=1, {ntb} ntr=1, restraint_wt=1.0, restraintmask={q},\n/\n"
    r = engine.run(text, prmtop, inpcrd, engine=eng, timeout=120)
    if r.timed_out:
        raise TimeoutError(mask)
    m = MATCHES.search(r.log)
    if m:
        return int(m.group(2)), ""
    return None, r.error


if __name__ == "__main__":
    top, crd, *masks = sys.argv[1:]
    with ThreadPoolExecutor(8) as ex:
        for mask, (n, err) in zip(masks, ex.map(lambda m: count(top, crd, m), masks)):
            print(f"{mask!r:40} {n if n is not None else 'REJECT ' + err}")
