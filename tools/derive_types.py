"""For each known &cntrl/&ewald name, ask the engine what kind of value it takes.

    python tools/derive_types.py [--engine pmemd sander]

name=0 reads -> it takes a number (and name=1.5 reads -> a real one); name='0' reads -> a string;
name=0, 0 reads -> a list.
Writes keys.json["types"][namelist][name] = "int" | "real" | "str" | "any" and ["arrays"][namelist].
Run after derive_keys.py, which supplies the names. A setting follows the probed one, so that a
failed read is reported as one (gfortran's runtime error, or sander's "error in reading namelist")
rather than as the "End of file" a bad value at the end of a group gives. The types differ between
the engines: timlim, for one, is an integer in pmemd and a real in sander.
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from derive_keys import READ_FAILED, SYSTEM, mdin  # noqa: E402
from mdin_check import engine  # noqa: E402


def reads(eng: str, nl: str, name: str, value: str) -> bool:
    """True if gfortran reads name=value. A setting follows it (ntpr / skinnb), because a bad value
    at the very end of a group is reported as "End of file" rather than by name; any gfortran
    runtime error is a failed read, while the engine's own "| ERROR:" checks come after reading."""
    after = "ntpr=1," if nl == "cntrl" else "verbose=0,"
    text = mdin(eng, nl, name, f"{value}, {after}")
    r = engine.run(text, SYSTEM / "solv.parm7", SYSTEM / "solv.rst7", engine=eng, timeout=120)
    if r.timed_out:
        raise TimeoutError(name)
    return "Fortran runtime error" not in r.log and not READ_FAILED.search(r.log)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", nargs="+", default=["pmemd", "sander"])
    ap.add_argument("--jobs", type=int, default=10)
    a = ap.parse_args()
    path = ROOT / "mdin_check" / "data" / "keys.json"
    table = json.loads(path.read_text())
    for eng in a.engine:
        types = table.setdefault("types", {})[eng] = {}
        arrays = table.setdefault("arrays", {})[eng] = {}
        for nl in ("cntrl", "ewald"):
            names = table.get(eng, {}).get(nl, [])

            def probe(n):
                num = reads(eng, nl, n, "0")
                return n, num, reads(eng, nl, n, "'0'"), reads(eng, nl, n, "0, 0"), num and reads(eng, nl, n, "1.5")

            with ThreadPoolExecutor(a.jobs) as ex:
                for n, num, s, arr, real in ex.map(probe, names):
                    # gfortran reads "1.5" into an integer as 1 and then fails on ".5": that is an integer
                    kind = "any" if num and s else ("real" if real else "int") if num else "str" if s else "any"
                    prev = types.setdefault(nl, {}).get(n)
                    types[nl][n] = kind if prev in (None, kind) else "any"
                    if arr:
                        arrays.setdefault(nl, [])
                        if n not in arrays[nl]:
                            arrays[nl].append(n)
            arrays.get(nl, []).sort()
            path.write_text(json.dumps(table, indent=1, sort_keys=True) + "\n")
            print(f"{eng} &{nl}: {len(names)} names typed", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
