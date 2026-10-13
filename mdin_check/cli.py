"""Command line: mdin-check FILE... [-p prmtop] [-c inpcrd] [--engine pmemd|sander] [--json] [--run]"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, engine, rules
from .topology import read_coordinates, read_prmtop

SEV = {"error": "error  ", "silent": "silent ", "warning": "warning", "info": "info   "}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="mdin-check",
        description="Check Amber sander/pmemd input files. Exit 0: nothing wrong; 1: an error (the engine refuses "
                    "the file) or a silent problem (it runs, but not as written); 2: could not check.")
    ap.add_argument("mdin", nargs="+", help="mdin file(s)")
    ap.add_argument("-p", "--prmtop", help="topology: enables mask, box and HMR checks")
    ap.add_argument("-c", "--inpcrd", help="coordinates/restart: enables distance masks and the cutoff-vs-box check")
    ap.add_argument("--engine", choices=["pmemd", "sander"], default="pmemd")
    ap.add_argument("--json", action="store_true", help="one JSON object per file, for programs and agents")
    ap.add_argument("--run", action="store_true",
                    help="also run the engine up to its first step (needs -p, -c and the engine installed) and "
                         "report whether it accepts the file")
    ap.add_argument("--no-policy", action="store_true", help="drop warnings (practice), keep error/silent/info")
    ap.add_argument("--strict", action="store_true", help="exit 1 on warnings too")
    ap.add_argument("-q", "--quiet", action="store_true", help="hide info findings in text output")
    ap.add_argument("--version", action="version", version=f"mdin-check {__version__}")
    a = ap.parse_args(argv)
    if a.run and not (a.prmtop and a.inpcrd):
        ap.error("--run needs -p and -c")

    try:
        top = read_prmtop(a.prmtop) if a.prmtop else None
        crd = read_coordinates(a.inpcrd, top.natom) if a.inpcrd and top else None
    except (OSError, ValueError, KeyError) as e:
        print(f"mdin-check: cannot read topology/coordinates: {e}", file=sys.stderr)
        return 2

    status = 0
    for path in a.mdin:
        try:
            text = Path(path).read_text(errors="replace")
        except OSError as e:
            print(f"mdin-check: {e}", file=sys.stderr)
            status = max(status, 2)
            continue
        rep = rules.check_text(text, a.engine, top, crd, policy=not a.no_policy)
        run = None
        if a.run:
            try:
                r = engine.run(text, a.prmtop, a.inpcrd, engine=a.engine)
                run = {"accepted": r.accepted, "error": r.error}
                if not r.accepted and rep.verdict != "reject":
                    rep.findings.insert(0, rules.Finding("ENGINE_REJECTED", "error",
                                                         f"{a.engine} refused the file: {r.error}"))
            except FileNotFoundError as e:
                run = {"accepted": None, "error": str(e)}
        bad = rep.verdict != "ok" or (a.strict and any(f.severity == "warning" for f in rep.findings))
        status = max(status, 1 if bad else 0)
        if a.json:
            d = {"file": path, **rep.to_dict()}
            if run is not None:
                d["engine_run"] = run
            print(json.dumps(d))
            continue
        _print(path, rep, run, a.quiet)
    return status


def _print(path: str, rep: rules.Report, run: dict | None, quiet: bool) -> None:
    d = rep.to_dict()
    c = d["counts"]
    head = {"reject": "REJECT", "suspect": "SUSPECT", "ok": "OK"}[rep.verdict]
    parts = [f"{c[s]} {s}" for s in ("error", "silent", "warning", "info") if c[s]]
    print(f"{path} ({rep.engine}): {head}" + (f" - {', '.join(parts)}" if parts else ""))
    for f in rep.findings:
        if quiet and f.severity == "info":
            continue
        loc = f"{path}:{f.line}" if f.line else path
        print(f"  {loc}: {SEV[f.severity]} {f.code}: {f.message}")
        if f.fix:
            print(f"      fix: {f.fix}")
    for m in rep.masks:
        kinds = ", ".join(f"{v} {k}" for k, v in sorted(m["by_kind"].items()))
        print(f"  mask {m['key']}='{m['mask']}': {m['atoms']} atoms in {m['residues']} residues"
              + (f" ({kinds})" if kinds else "") + (f"; first: {' '.join(m['first_residues'])}" if m['atoms'] else ""))
    if run is not None:
        verdict = "accepted" if run["accepted"] else "not run" if run["accepted"] is None else "REFUSED"
        print(f"  engine run: {verdict}" + (f" - {run['error']}" if run["error"] else ""))


if __name__ == "__main__":
    sys.exit(main())
