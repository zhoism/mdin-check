"""Derive the names each engine accepts in each namelist, by asking the engine.

    python tools/derive_keys.py candidates.txt [--engine pmemd sander] [--jobs 10]

Each candidate name is written alone into a namelist (`name=0`) and the engine is run on it.
gfortran rejects an unknown name with "Cannot match namelist object name <name>" while it
reads the namelist, before any value is checked, so every other outcome (accepted, or any
other error) means the engine knows the name. The candidates are any word list; the one used
for the shipped tables is every identifier in the Amber 2026 reference manual plus ParmEd's
mdin tables. Writes mdin_check/data/keys.json, merged with what is already there.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from mdin_check import engine  # noqa: E402

SYSTEM = ROOT / "tests" / "systems"
BASE = ("probe\n&cntrl\n imin=0, nstlim=2, dt=0.002, ntc=2, ntf=2, cut=9.0, ntb=1, ntt=3, gamma_ln=2.0,"
        " temp0=300.0, ig=-1, ntpr=1, {extra}\n/\n")

# How to make each engine read each namelist: (extra &cntrl settings, text before, text after).
NAMELISTS = {
    "pmemd": {
        "cntrl": ("", None, ""),
        "ewald": ("", "ewald", ""),
        "wt": ("nmropt=1,", "wt", "&wt type='END' /\n"),
    },
    "sander": {
        "cntrl": ("", None, ""),
        "ewald": ("", "ewald", ""),
        "wt": ("nmropt=1,", "wt", "&wt type='END' /\n"),
        "qmmm": ("ifqnt=1,", "qmmm", ""),
    },
}


def mdin(eng: str, nl: str, name: str, value: str = "0") -> str:
    extra, block, after = NAMELISTS[eng][nl]
    if block is None:
        return BASE.format(extra=f"{extra} {name}={value},")
    if nl == "wt":
        return BASE.format(extra=extra) + f"&wt {name}={value}, /\n" + after
    if nl == "qmmm":
        return BASE.format(extra=extra) + f"&qmmm qmmask=':1', {name}={value}, /\n"
    return BASE.format(extra=extra) + f"&{block}\n {name}={value},\n/\n" + after


# pmemd's reads name the unknown object. sander reads with iostat and says only that the
# namelist failed, which a type mismatch also causes, so a name counts as unknown to sander
# only when both an integer and a quoted string fail to read.
READ_FAILED = re.compile(r"Cannot match namelist object name|error in reading namelist|Problem reading &|"
                         r"Error (in|reading) &?\w+ namelist", re.I)


def run(eng: str, text: str):
    """The engine's result; a run killed at the timeout says nothing, so it is retried, then raises."""
    for timeout in (60, 300):
        r = engine.run(text, SYSTEM / "solv.parm7", SYSTEM / "solv.rst7", engine=eng, timeout=timeout)
        if not r.timed_out:
            return r
    raise TimeoutError(text)


def known(eng: str, nl: str, name: str) -> bool:
    for value in ("0", "'0'"):
        r = run(eng, mdin(eng, nl, name, value))
        if f"Cannot match namelist object name {name}" in r.log:
            return False
        if r.accepted or not READ_FAILED.search(r.log):
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("candidates")
    ap.add_argument("--engine", nargs="+", default=["pmemd", "sander"])
    ap.add_argument("--namelist", nargs="+", help="only these namelists (default: all for each engine)")
    ap.add_argument("--jobs", type=int, default=10)
    ap.add_argument("--replace", action="store_true", help="replace each table instead of adding to it")
    a = ap.parse_args()
    words = sorted({w.strip().lower() for w in open(a.candidates) if w.strip()})
    out_path = ROOT / "mdin_check" / "data" / "keys.json"
    table = json.loads(out_path.read_text()) if out_path.exists() else {}
    out_path.parent.mkdir(exist_ok=True)
    for eng in a.engine:
        for nl in a.namelist or NAMELISTS[eng]:
            if nl not in NAMELISTS[eng]:
                continue
            with ThreadPoolExecutor(a.jobs) as ex:
                ok = [w for w, k in zip(words, ex.map(lambda w: known(eng, nl, w), words)) if k]
            prev = set() if a.replace else set(table.get(eng, {}).get(nl, []))
            table.setdefault(eng, {})[nl] = sorted(prev | set(ok))
            out_path.write_text(json.dumps(table, indent=1, sort_keys=True) + "\n")
            print(f"{eng} &{nl}: {len(ok)} of {len(words)} candidates known", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
