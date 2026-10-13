import json
from pathlib import Path

from mdin_check.cli import main

SYS = Path(__file__).parent / "systems"


def write(tmp_path, text, name="x.in"):
    p = tmp_path / name
    p.write_text(text)
    return str(p)


def test_exit_codes(tmp_path, capsys):
    ok = write(tmp_path, "t\n&cntrl\n imin=1, maxcyc=10, ntb=1, cut=9.0,\n/\n", "ok.in")
    bad = write(tmp_path, "t\n&cntrl\n imin=1, maxcyc=10, ntb=1, cut=9.0, ntr=1,\n/\n", "bad.in")
    silent = write(tmp_path, "t\n&cntrl\n imin=1, maxcyc=10, ntb=1, cut=9.0, restraintmask=':1',\n/\n", "s.in")
    assert main([ok]) == 0
    assert main([bad]) == 1
    assert main([silent]) == 1
    assert main([str(tmp_path / "missing.in")]) == 2
    capsys.readouterr()


def test_json_is_one_object_per_file(tmp_path, capsys):
    a = write(tmp_path, "t\n&cntrl\n imin=1, maxcyc=10, ntb=1, cut=9.0,\n/\n", "a.in")
    b = write(tmp_path, "t\n&cntrl\n imin=1, ntb=1, cut=9.0, ntt=1, gamma_ln=1.0,\n/\n", "b.in")
    main([a, b, "--json", "-p", str(SYS / "solv.parm7"), "-c", str(SYS / "solv.rst7")])
    lines = capsys.readouterr().out.strip().splitlines()
    docs = [json.loads(x) for x in lines]
    assert [d["file"] for d in docs] == [a, b]
    assert docs[0]["verdict"] == "ok" and docs[1]["verdict"] == "reject"
    assert {"code", "severity", "message", "line", "fix"} <= set(docs[1]["findings"][0])


def test_strict_and_no_policy(tmp_path, capsys):
    w = write(tmp_path, "t\n&cntrl\n imin=0, nstlim=10, dt=0.004, ntc=2, ntf=2, ntb=1, cut=9.0, ntt=3, "
                        "gamma_ln=2.0, ig=-1,\n/\n")
    assert main([w]) == 0
    assert main([w, "--strict"]) == 1
    assert main([w, "--strict", "--no-policy"]) == 0
    capsys.readouterr()


def test_mask_report(tmp_path, capsys):
    m = write(tmp_path, "t\n&cntrl\n imin=1, maxcyc=10, ntb=1, cut=9.0, ntr=1, restraint_wt=5.0, "
                        "restraintmask='!:WAT&!@H=',\n/\n")
    main([m, "--json", "-p", str(SYS / "solv.parm7")])
    d = json.loads(capsys.readouterr().out)
    assert d["masks"][0]["atoms"] > 0 and "water" not in d["masks"][0]["by_kind"]
