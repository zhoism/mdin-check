"""Inputs with a known engine verdict, used two ways.

test_rules.py checks that mdin-check reports each case's codes. test_vs_engine.py runs each
case through the engine and checks the recorded verdict ("accept" or "reject") still holds,
and that mdin-check's own verdict agrees with it: a case the engine rejects must carry an
error, and a case it accepts must carry none.
"""
from __future__ import annotations

from dataclasses import dataclass, field

BASE = dict(imin=0, irest=0, ntx=1, nstlim=2, dt=0.002, ntc=2, ntf=2, cut=9.0, ntb=1, ntt=3, gamma_ln=2.0,
            temp0=300.0, tempi=300.0, ig=-1, ntpr=1)


def mdin(over: dict | None = None, drop: tuple = (), after: str = "", title: str = "case") -> str:
    d = dict(BASE)
    d.update(over or {})
    for k in drop:
        d.pop(k, None)
    body = ", ".join(f"{k}={v}" for k, v in d.items())
    return f"{title}\n&cntrl\n {body},\n/\n{after}"


@dataclass
class Case:
    name: str
    text: str
    engine_verdict: str              # what the engine does: "accept" | "reject"
    codes: list[str] = field(default_factory=list)   # codes mdin-check must report
    engines: tuple = ("pmemd", "sander")
    system: str = "solv"              # solv | vac
    crd: str = "solv.rst7"
    severity: dict = field(default_factory=dict)      # code -> required severity


WT_END = "&wt type='END' /\n"
V = "solv_vel.rst7"

CASES = [
    Case("baseline", mdin(), "accept"),
    # structure
    Case("tab before &cntrl", "t\n\t&cntrl\n imin=0, nstlim=2, cut=9.0, ntb=1,\n/\n", "reject", ["NO_CNTRL"]),
    Case("nbsp before &cntrl", "t\n &cntrl\n imin=0, nstlim=2, cut=9.0, ntb=1,\n/\n", "reject", ["NO_CNTRL"]),
    Case("&cntrl past column 80", "t\n" + " " * 79 + "&cntrl\n imin=0, nstlim=2, cut=9.0, ntb=1,\n/\n", "reject",
         ["NO_CNTRL"]),
    Case("tab before &ewald", mdin(after="\t&ewald\n skinnb=1.0,\n/\n"), "accept", ["HIDDEN_NAMELIST"],
         severity={"HIDDEN_NAMELIST": "silent"}),
    Case("no title, pmemd", mdin().split("\n", 1)[1], "accept", ["NO_TITLE"], engines=("pmemd",),
         severity={"NO_TITLE": "info"}),
    Case("no title, sander", mdin().split("\n", 1)[1], "reject", ["NO_TITLE"], engines=("sander",)),
    Case("&cntrlx", mdin().replace("&cntrl", "&cntrlx"), "reject", ["NAMELIST_NAME"]),
    Case("&ewaldx, pmemd", mdin(after="&ewaldx\n skinnb=1.0,\n/\n"), "reject", ["NAMELIST_NAME"], engines=("pmemd",)),
    Case("&ewaldx, sander", mdin(after="&ewaldx\n skinnb=1.0,\n/\n"), "accept", ["NAMELIST_UNKNOWN"],
         engines=("sander",)),
    Case("&ewlad typo", mdin(after="&ewlad\n skinnb=1.0,\n/\n"), "accept", ["NAMELIST_UNKNOWN"]),
    Case("&debugf in pmemd", mdin(after="&debugf\n do_debugf=0,\n/\n"), "reject", ["NAMELIST_REJECTED"],
         engines=("pmemd",)),
    Case("unknown key in an ignored &wt", mdin(after="&wt type='TEMP0', bogus=1 /\n" + WT_END), "accept",
         ["NAMELIST_IGNORED"]),
    Case("&wt with nmropt=0", mdin(after="&wt type='TEMP0', istep1=0, istep2=2, value1=0.0, value2=300.0 /\n" + WT_END),
         "accept", ["NAMELIST_IGNORED"]),
    Case("second &cntrl", mdin() + "&cntrl\n dt=0.004,\n/\n", "accept", ["DUPLICATE_NAMELIST"]),
    Case("&end terminator", mdin().replace("\n/\n", "\n&end\n"), "accept"),
    Case("$end terminator", mdin().replace("\n/\n", "\n$end\n"), "accept"),
    Case("slash in a comment", "t\n&cntrl\n imin=0, nstlim=2, dt=0.002, ! 2 fs/step\n cut=15.0, ntb=1, ntc=2, ntf=2,\n/\n",
         "reject", ["CUT_BOX"]),
    Case("tab after &cntrl, sander", mdin().replace("&cntrl\n", "&cntrl\t! note\n"), "reject", ["NAMELIST_NAME_END"],
         engines=("sander",)),
    Case("comment right after &cntrl, sander", mdin().replace("&cntrl\n", "&cntrl! note\n"), "reject",
         ["NAMELIST_NAME_END"], engines=("sander",)),
    Case("tab after &cntrl, pmemd", mdin().replace("&cntrl\n", "&cntrl\t! note\n"), "accept", engines=("pmemd",)),
    Case("space and comment after &cntrl", mdin().replace("&cntrl\n", "&cntrl ! note\n"), "accept"),
    Case("CRLF line ends", mdin().replace("\n", "\r\n"), "accept"),
    Case("no line break after the last '/'", mdin().rstrip("\n"), "reject", ["NO_FINAL_NEWLINE"]),
    Case("no line break after '&end'", mdin().rstrip("\n")[:-1] + "&end", "reject", ["NO_FINAL_NEWLINE"]),
    Case("no line break after &wt END", mdin({"nmropt": 1}, after="&wt type='END' /"), "reject",
         ["NO_FINAL_NEWLINE"]),
    Case("text after the last namelist, no final break", mdin() + "DISANG=x", "accept"),
    Case("unread &wt last, no final break", mdin(after="&wt type='END' /"), "accept", ["NAMELIST_IGNORED"]),
    # keys and values
    Case("unknown key", mdin({"ntsx": 1}), "reject", ["UNKNOWN_KEY"]),
    Case("pmemd-only key in sander", mdin({"ramdproteinmask": "':1'"}), "reject", ["UNKNOWN_KEY"], engines=("sander",)),
    Case("unknown key in &ewald", mdin(after="&ewald\n bogus=1,\n/\n"), "reject", ["UNKNOWN_KEY"]),
    Case("value without key", "t\n&cntrl\n imin=0, nstlim=2 3, ntb=1, cut=9.0,\n/\n", "reject", ["VALUE_WITHOUT_KEY"]),
    Case("unquoted mask", mdin({"ntr": 1, "restraint_wt": 2.0, "restraintmask": ":1-10@CA"}), "reject", ["BAD_VALUE"]),
    Case("logical for an integer flag", mdin({"ntr": ".true.", "restraintmask": "':1-10'"}), "reject", ["BAD_VALUE"]),
    Case("quoted number", mdin({"dt": "'0.002'"}), "reject", ["BAD_VALUE"]),
    Case("empty value", "t\n&cntrl\n imin=0, nstlim=2, dt=, ntb=1, cut=9.0,\n/\n", "accept", ["EMPTY_VALUE"]),
    Case("repeated key", mdin({"dt": 0.002}) .replace("dt=0.002,", "dt=0.004, dt=0.002,"), "accept", ["DUPLICATE_KEY"]),
    Case("Fortran d exponent", mdin({"dt": "2.0d-3"}), "accept"),
    # domains (pmemd)
    Case("imin=5, pmemd", mdin({"imin": 5}), "reject", ["VALUE_DOMAIN"], engines=("pmemd",)),
    Case("nmropt=2, pmemd", mdin({"nmropt": 2}, after=WT_END), "reject", ["VALUE_DOMAIN"], engines=("pmemd",)),
    Case("ntt=4, pmemd", mdin({"ntt": 4}, drop=("gamma_ln",)), "reject", ["VALUE_DOMAIN"], engines=("pmemd",)),
    Case("idecomp=1, pmemd", mdin({"idecomp": 1}), "reject", ["VALUE_DOMAIN"], engines=("pmemd",)),
    Case("ifqnt=1, pmemd", mdin({"ifqnt": 1}), "reject", ["VALUE_DOMAIN"], engines=("pmemd",)),
    Case("ntt=4, sander", mdin({"ntt": 4}, drop=("gamma_ln",)), "accept", engines=("sander",)),
    Case("ntt=11", mdin({"ntt": 11}, drop=("gamma_ln",)), "accept"),
    Case("ntt=-1", mdin({"ntt": -1}, drop=("gamma_ln",)), "reject", ["VALUE_DOMAIN"]),
    Case("ntc=4, pmemd", mdin({"ntc": 4}), "reject", ["VALUE_DOMAIN"], engines=("pmemd",)),
    Case("ntc=0", mdin({"ntc": 0}), "reject", ["VALUE_DOMAIN"]),
    Case("ntf=9", mdin({"ntf": 9}), "reject", ["VALUE_DOMAIN"]),
    Case("ntx=3, pmemd", mdin({"ntx": 3}), "reject", ["VALUE_DOMAIN"], engines=("pmemd",)),
    Case("ntx=2, pmemd", mdin({"ntx": 2}), "accept", ["NTX_LEGACY"], engines=("pmemd",)),
    Case("ntxo=0", mdin({"ntxo": 0}), "reject", ["VALUE_DOMAIN"]),
    Case("ioutfm=2", mdin({"ioutfm": 2}), "reject", ["VALUE_DOMAIN"]),
    Case("iwrap=2, pmemd", mdin({"iwrap": 2}), "reject", ["VALUE_DOMAIN"], engines=("pmemd",)),
    Case("ntwx=-1", mdin({"ntwx": -1}), "reject", ["VALUE_DOMAIN"]),
    Case("igb=3", mdin({"igb": 3, "ntb": 0, "cut": 999.0}), "reject", ["VALUE_DOMAIN"]),
    Case("ntp=4, sander", mdin({"ntp": 4, "ntb": 2}), "reject", ["VALUE_DOMAIN"], engines=("sander",)),
    Case("barostat=3, sander", mdin({"ntp": 1, "ntb": 2, "barostat": 3}), "reject", ["VALUE_DOMAIN"],
         engines=("sander",)),
    Case("barostat=3 with ntp=0, sander", mdin({"barostat": 3}), "accept", engines=("sander",)),
    Case("cut=-1, pmemd", mdin({"cut": -1.0}), "reject", ["VALUE_DOMAIN"], engines=("pmemd",)),
    Case("cut=0, pmemd", mdin({"cut": 0.0}), "accept", ["CUT"], engines=("pmemd",)),
    # cross-key
    Case("irest=1 with ntx=1", mdin({"irest": 1, "ntx": 1}), "reject", ["RESTART"]),
    Case("irest=1 with ntx=2", mdin({"irest": 1, "ntx": 2}), "reject", ["RESTART"], crd=V),
    Case("irest=1 with ntx=5", mdin({"irest": 1, "ntx": 5}), "accept", crd=V),
    Case("gamma_ln with ntt=1", mdin({"ntt": 1}), "reject", ["THERMOSTAT"]),
    Case("gamma_ln with ntt=0", mdin({"ntt": 0}), "reject", ["THERMOSTAT"]),
    Case("ntt=3 gamma_ln=0", mdin({"gamma_ln": 0.0}), "accept", ["THERMOSTAT_OFF"]),
    Case("ntt=3 no gamma_ln", mdin(drop=("gamma_ln",)), "accept", ["THERMOSTAT_OFF"]),
    Case("ntp=1 with ntb=1", mdin({"ntp": 1}), "reject", ["PRESSURE"]),
    Case("ntb=2 with ntp=0", mdin({"ntb": 2}), "reject", ["PRESSURE"]),
    Case("ntp=1 with ntb unset", mdin({"ntp": 1}, drop=("ntb",)), "accept"),
    Case("ntp=3 without csurften", mdin({"ntp": 3, "ntb": 2, "csurften": 0}), "reject", ["PRESSURE"]),
    Case("MC barostat, mcbarint > nstlim, pmemd", mdin({"ntp": 1, "ntb": 2, "barostat": 2}), "reject", ["PRESSURE"],
         engines=("pmemd",)),
    Case("igb=1 with ntb=1, sander", mdin({"igb": 1}), "reject", ["GB_PERIODIC"], engines=("sander",)),
    Case("igb=1 with ntb=1, pmemd", mdin({"igb": 1}), "accept", ["GB_PERIODIC"], engines=("pmemd",)),
    Case("ntc=1 ntf=2", mdin({"ntc": 1, "ntf": 2, "dt": 0.001}), "accept", ["SHAKE_MISMATCH"],
         severity={"SHAKE_MISMATCH": "silent"}),
    Case("ntc=2 ntf=3", mdin({"ntc": 2, "ntf": 3}), "accept", ["SHAKE_MISMATCH"], severity={"SHAKE_MISMATCH": "silent"}),
    Case("dt=0", mdin({"dt": 0.0}), "accept", ["DT"], severity={"DT": "silent"}),
    Case("dt<0", mdin({"dt": -0.002}), "accept", ["DT"], severity={"DT": "silent"}),
    Case("dt=0.004 no HMR", mdin({"dt": 0.004}), "accept", ["DT"], severity={"DT": "warning"}),
    Case("nstlim=0", mdin({"nstlim": 0}), "accept", ["NSTLIM"]),
    Case("cut over half the box", mdin({"cut": 14.0}), "reject", ["CUT_BOX"], engines=("pmemd",)),
    Case("cut just inside, pmemd", mdin({"cut": 13.0}), "accept", engines=("pmemd",)),
    Case("cut over half the box minus skin, sander", mdin({"cut": 13.0}), "reject", ["CUT_BOX"], engines=("sander",)),
    Case("vacuum on a periodic topology", mdin({"ntb": 0, "cut": 12.0}), "accept", ["VACUUM_BOX"]),
    Case("periodic run on coordinates with no box", mdin({"imin": 1, "maxcyc": 1}), "reject", ["NO_BOX"],
         system="vac", crd="vac.rst7"),
    Case("ntwx > nstlim", mdin({"ntwx": 10}), "accept", ["OUTPUT"]),
    # &wt
    Case("nmropt=1 without END", mdin({"nmropt": 1},
                                      after="&wt type='TEMP0', istep1=0, istep2=2, value1=0.0, value2=300.0 /\n"),
         "reject", ["WT_END"]),
    Case("bad &wt type", mdin({"nmropt": 1}, after="&wt type='TEMP', istep1=0, istep2=2, value1=0.0, value2=300.0 /\n"
                              + WT_END), "reject", ["WT_TYPE"]),
    Case("CUT type, pmemd", mdin({"nmropt": 1}, after="&wt type='CUT', istep1=0, istep2=2, value1=8.0, value2=9.0 /\n"
                                 + WT_END), "reject", ["WT_TYPE"], engines=("pmemd",)),
    Case("ramp past nstlim", mdin({"nmropt": 1}, after="&wt type='TEMP0', istep1=0, istep2=1000, value1=0.0, "
                                  "value2=300.0 /\n" + WT_END), "accept", ["WT_RAMP"]),
    Case("ramp to a different temp0", mdin({"nmropt": 1, "temp0": 310.0}, after="&wt type='TEMP0', istep1=0, "
                                           "istep2=2, value1=0.0, value2=300.0 /\n" + WT_END), "accept", ["WT_RAMP"],
         severity={"WT_RAMP": "warning"}),
    # restraints, belly, masks
    Case("restraintmask with ntr=0", mdin({"restraintmask": "':1-10'", "restraint_wt": 2.0}), "accept",
         ["MASK_IGNORED"]),
    Case("bellymask with ibelly=0", mdin({"bellymask": "':1-10'"}), "accept", ["MASK_IGNORED"]),
    Case("ntr=1 with no mask or group", mdin({"ntr": 1, "restraint_wt": 2.0}), "reject", ["GROUP_INPUT"]),
    Case("ibelly=1 with no mask or group", mdin({"ibelly": 1, "ntt": 1}, drop=("gamma_ln",)), "reject",
         ["GROUP_INPUT"]),
    Case("ibelly=1 with ntt=3, pmemd", mdin({"ibelly": 1, "bellymask": "':1-10'"}), "reject", ["BELLY"],
         engines=("pmemd",)),
    Case("restraint weight 0", mdin({"ntr": 1, "restraintmask": "':1-10'"}), "accept", ["RESTRAINT_WEIGHT"]),
    Case("mask with '.'", mdin({"ntr": 1, "restraint_wt": 2.0, "restraintmask": "':1-10@CA.C.N'"}), "reject",
         ["MASK_SYNTAX"]),
    Case("mask glob", mdin({"ntr": 1, "restraint_wt": 2.0, "restraintmask": "'@H*'"}), "reject", ["MASK_SYNTAX"]),
    Case("mask cpptraj element", mdin({"ntr": 1, "restraint_wt": 2.0, "restraintmask": "'@/H'"}), "reject",
         ["MASK_SYNTAX"]),
    Case("mask repeated colon", mdin({"ntr": 1, "restraint_wt": 2.0, "restraintmask": "':1,:3'"}), "reject",
         ["MASK_SYNTAX"]),
    Case("mask type wildcard", mdin({"ntr": 1, "restraint_wt": 2.0, "restraintmask": "'@%C='"}), "reject",
         ["MASK_SYNTAX"]),
    Case("mask VMD", mdin({"ntr": 1, "restraint_wt": 2.0, "restraintmask": "'protein and name CA'"}), "reject",
         ["MASK_SYNTAX"]),
    Case("mask too long, sander", mdin({"ntr": 1, "restraint_wt": 2.0,
                                        "restraintmask": "'" + ",".join([":1"] + [str(i) for i in range(2, 120)]) + "'"}),
         "reject", ["MASK_LENGTH"], engines=("sander",)),
    Case("mask HOH", mdin({"ntr": 1, "restraint_wt": 2.0, "restraintmask": "'!:HOH&!@H='"}), "accept",
         ["MASK_NAME"]),
    Case("mask selects nothing", mdin({"ntr": 1, "restraint_wt": 2.0, "restraintmask": "':HOH'"}), "accept",
         ["MASK_EMPTY"]),
    Case("mask @H", mdin({"ntr": 1, "restraint_wt": 2.0, "restraintmask": "':1-10&!@H'"}), "accept", ["MASK_H"]),
    Case("mask backbone unrestricted", mdin({"ntr": 1, "restraint_wt": 2.0, "restraintmask": "'@CA,C,N,O'"}),
         "accept", ["MASK_SOLVENT"]),
    Case("mask juxtaposed", mdin({"ntr": 1, "restraint_wt": 2.0, "restraintmask": "'(:1-3)@CA'"}), "accept",
         ["MASK_JUXTAPOSED"]),
    Case("mask mixed list", mdin({"ntr": 1, "restraint_wt": 2.0, "restraintmask": "':1,ALA'"}), "accept",
         ["MASK_MIXED_LIST"]),
    Case("mask double negation", mdin({"ntr": 1, "restraint_wt": 2.0, "restraintmask": "'!!:1'"}), "reject",
         ["MASK_SYNTAX"], engines=("pmemd",)),
    Case("mask name of 5 characters", mdin({"ntr": 1, "restraint_wt": 2.0, "restraintmask": "':ABCDE'"}), "reject",
         ["MASK_SYNTAX"], engines=("pmemd",)),
    Case("mask template placeholder", mdin({"ntr": 1, "restraint_wt": 2.0, "restraintmask": "':1-TOTRES'"}), "reject",
         ["MASK_SYNTAX"], engines=("pmemd",)),
    Case("mask name of 4 characters", mdin({"ntr": 1, "restraint_wt": 2.0, "restraintmask": "':ABCD'"}), "accept",
         ["MASK_EMPTY"], engines=("pmemd",)),
    Case("mask ok", mdin({"ntr": 1, "restraint_wt": 2.0, "restraintmask": "':1-10@CA'"}), "accept"),
]
