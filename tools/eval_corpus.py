"""Score mdin-check against the engine on a corpus of real mdin files.

    python tools/eval_corpus.py corpus [--engine pmemd] [--jobs 10] [--out results/corpus_pmemd.json]

Each file is checked statically (no topology: the files were written for other systems), and
run through the engine on one of the test systems: periodic runs on the solvated peptide,
ntb=0 runs on the vacuum one, restarts on the copy with velocities. A file can fail in the
engine because it names something only its own system has (an input file, more atoms, a
CV file); those are classed as "environment" and left out of the score, with the engine's
message kept so the class can be audited.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from mdin_check import engine, rules  # noqa: E402
from mdin_check.namelist import parse  # noqa: E402

SYS = ROOT / "tests" / "systems"
CAP = 5

# Engine messages that mean "this file needs its own system or files", not "the input is wrong".
ENVIRONMENT = re.compile(
    r"could not find enough velocities|cannot open|could not open|No such file|file not found|does not exist|"
    r"Error opening|DISANG|LISTIN|LISTOUT|DUMPAVE|out of range|number of atoms|natom|cpin|cein|groupfile|"
    r"numgroup|must be compiled|recompile|GPU|cuda|MPI|parallel|linearly scaled atoms|does not have match|"
    r"must exsit|must exist|radius .* outside|Error on OPEN|OPNMRG|does not have match|must match at least one atom|"
    r"External program|max pairlist cutoff|half smallest box|ew_legal|Regenerate prmtop|larger box", re.I)


def system_for(text: str) -> tuple[Path, Path]:
    md = parse(text)
    c = md.first("cntrl")
    get = (lambda k, d=None: c.value(k, d)) if c else (lambda k, d=None: d)
    ntb, igb, ntp = get("ntb"), get("igb", 0) or 0, get("ntp", 0) or 0
    periodic = ntb != 0 if isinstance(ntb, int) else not (isinstance(igb, int) and igb > 0) or (ntp or 0) > 0
    restart = get("ntx", 1) in (4, 5, 6, 7) or get("irest", 0) == 1
    if periodic:
        return SYS / "solv.parm7", SYS / ("solv_vel.rst7" if restart else "solv.rst7")
    return SYS / "vac.parm7", SYS / ("vac_vel.rst7" if restart else "vac.rst7")


def one(path: Path, eng: str) -> dict:
    text = path.read_text(errors="replace")
    rep = rules.check_text(text, eng)
    top, crd = system_for(text)
    try:
        r = engine.run(text, top, crd, engine=eng, timeout=120)
        accepted, err = (None if r.timed_out else r.accepted), r.error
    except Exception as e:  # noqa: BLE001 - a crash in the harness is recorded, not raised
        accepted, err = None, f"harness: {e}"
    static = rep.verdict
    # an error inside a namelist the engine may not read on this test system cannot be confirmed by it
    read = {"cntrl", "ewald", "wt", None}
    confirmable = [f for f in rep.findings if f.severity == "error" and f.namelist in read]
    if accepted is None:
        outcome = "timeout" if "timed out" in (err or "") else "harness"
    elif accepted:
        outcome = "agree" if static != "reject" else "false_alarm" if confirmable else "unverifiable"
    elif static == "reject":
        outcome = "agree"
    elif ENVIRONMENT.search(err or ""):
        outcome = "environment"
    else:
        outcome = "miss"
    return {"file": path.name, "outcome": outcome, "static": static, "engine_accepted": accepted,
            "engine_error": err, "codes": sorted({f.code + ":" + f.severity for f in rep.findings}),
            "errors": [f.message for f in rep.findings if f.severity == "error"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus")
    ap.add_argument("--engine", default="pmemd")
    ap.add_argument("--jobs", type=int, default=10)
    ap.add_argument("--out")
    a = ap.parse_args()
    files = sorted(Path(a.corpus).glob("*.in"))
    with ThreadPoolExecutor(a.jobs) as ex:
        res = list(ex.map(lambda p: one(p, a.engine), files))
    man_path = Path(a.corpus) / "manifest.json"
    manifest = json.loads(man_path.read_text()) if man_path.exists() else {}
    for r in res:
        r["repo"] = manifest.get(r["file"][:-3], {}).get("repo")
    tally = Counter(r["outcome"] for r in res)
    # one repository can supply hundreds of near-identical files; the capped tally counts at most CAP per repo
    per_repo: Counter = Counter()
    capped: Counter = Counter()
    for r in res:
        per_repo[r["repo"]] += 1
        if per_repo[r["repo"]] <= CAP:
            capped[r["outcome"]] += 1
    scored = tally["agree"] + tally["false_alarm"] + tally["miss"]
    findings = Counter(c for r in res for c in r["codes"])
    cscored = capped["agree"] + capped["false_alarm"] + capped["miss"]
    summary = {"engine": a.engine, "files": len(res), "repos": len(per_repo), "outcomes": dict(tally),
               "agreement_on_scored": round(tally["agree"] / scored, 4) if scored else None,
               f"outcomes_max_{CAP}_per_repo": dict(capped),
               f"agreement_max_{CAP}_per_repo": round(capped["agree"] / cscored, 4) if cscored else None,
               "findings_by_code": dict(findings.most_common())}
    print(json.dumps(summary, indent=1))
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps({"summary": summary, "files": res}, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
