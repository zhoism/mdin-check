"""Break each guarded rule in turn and check that the static suite goes red.

    python tools/mutate.py        (from the repo root)

Each mutant must be KILLED by a failing test. The baseline must be green first, and the
bytecode caches are cleared around every swap: a mutant the same size as the original,
restored within the same second, is otherwise still run from a stale .pyc.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

os.chdir(Path(__file__).resolve().parent.parent)

def clear():
    for d in Path(".").rglob("__pycache__"):
        if ".venv" not in d.parts:
            shutil.rmtree(d)

CMD = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
       "tests/test_rules.py", "tests/test_mask.py", "tests/test_namelist.py", "tests/test_cli.py"]
clear()
base = subprocess.run(CMD, capture_output=True, text=True)
assert base.returncode == 0, "baseline is not green:\n" + base.stdout[-500:]
print("baseline green:", base.stdout.strip().splitlines()[-1])
# (file, original text, mutant text)
MUTANTS = [
 ("mdin_check/namelist.py", 'if namelists and namelists[-1].terminator and "\\n" not in text[namelists[-1].end_pos:]:', 'if False:'),
 ("mdin_check/rules.py", 'if md_run and ntt == 3 and gamma <= 0:', 'if md_run and ntt == 3 and gamma < 0:'),
 ("mdin_check/rules.py", 'if irest == 1 and ntx in (1, 2):', 'if irest == 1 and ntx in (1,):'),
 ("mdin_check/rules.py", 'if cut + skin > half + 0.01:', 'if cut > half:'),
 ("mdin_check/rules.py", 'if ntc in level and ntf in level and level[ntf] > level[ntc]:', 'if ntc in level and ntf in level and level[ntf] > level[ntc] + 1:'),
 ("mdin_check/mask.py", 'if len(x) > 4 and x != "*":', 'if len(x) > 5 and x != "*":'),
 ("mdin_check/mask.py", '                left = operand()\n', '                left = left | operand()\n'),
 ("mdin_check/mask.py", 'near = _res_atoms(top, {top.atom_res[a] for a in near})\n    return near', 'pass\n    return near'),
 ("mdin_check/namelist.py", 's = line[:80].lstrip(" ")', 's = line[:80].lstrip(" \\t")'),
 ("mdin_check/rules.py", 'if c.has("restraintmask") and ntr == 0:', 'if c.has("restraintmask") and ntr == 2:'),
 ("mdin_check/rules.py", 'if known is not None and e.key not in known:', 'if known is not None and e.key not in known and len(e.key) > 4:'),
 ("mdin_check/rules.py", 'and _numeric_key(c, nl.name, e.key) and _looks_number(v.value):', 'and False:'),
 ("mdin_check/rules.py", 'len(e.values) > 1 and e.key not in arrays', 'len(e.values) > 2 and e.key not in arrays'),
]
for path, a, b in MUTANTS:
    p = Path(path); orig = p.read_text()
    assert a in orig, (path, a)
    p.write_text(orig.replace(a, b, 1))
    clear()
    try:
        r = subprocess.run(CMD + ["-x"], capture_output=True, text=True)
        failed = [l for l in r.stdout.splitlines() if l.startswith("FAILED")]
        print("KILLED " if r.returncode == 1 and failed else "SURVIVED" if r.returncode == 0 else f"ERROR rc={r.returncode}",
              path, a[:50].replace("\n", " "), "|", failed[0][:90] if failed else "")
    finally:
        p.write_text(orig)
        clear()
