"""The checks. Each finding has a severity that says what the engine will do:

  error    the engine refuses the file (it stops before the first step)
  silent   the engine runs, but something you wrote is ignored or means something else
  warning  the engine runs it as written; the setting is outside common practice
  info     worth knowing; nothing is wrong

"error" and "silent" claims are each tied to a probe of the real engine in
tests/test_engine_facts.py. "warning" is opinion (the defaults in POLICY) and can be
switched off with policy=False.
"""
from __future__ import annotations

import difflib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import mask as maskmod
from .namelist import Mdin, Namelist, parse
from .topology import Coordinates, Topology

DATA = Path(__file__).parent / "data"
FACTS = json.loads((DATA / "engine_facts.json").read_text())
KEYS = json.loads((DATA / "keys.json").read_text()) if (DATA / "keys.json").exists() else {}

POLICY = {
    "dt_max_no_shake": 0.001,     # ps, ntc=1
    "dt_max_shake": 0.002,        # ps, ntc=2 or 3
    "dt_max_hmr": 0.004,          # ps, hydrogen mass repartitioning
    "cut_min_pme": 8.0,           # Angstrom
}

MASK_KEYS = {"restraintmask", "bellymask", "timask1", "timask2", "scmask1", "scmask2", "noshakemask", "crgmask",
             "ramdproteinmask", "ramdligmask", "mcwatmask", "gti_cpu_output_mask", "emil_mask", "qmmask", "iwrap_mask",
             "gamd_ligmask", "cofacmask", "ligmask", "idsmask", "bbmask"}


@dataclass
class Finding:
    code: str
    severity: str
    message: str
    line: int | None = None
    namelist: str | None = None
    key: str | None = None
    fix: str | None = None


@dataclass
class Report:
    engine: str
    findings: list[Finding] = field(default_factory=list)
    masks: list[dict] = field(default_factory=list)   # what each mask selects, when a topology was given

    @property
    def verdict(self) -> str:
        sev = {f.severity for f in self.findings}
        return "reject" if "error" in sev else "suspect" if "silent" in sev else "ok"

    def to_dict(self) -> dict:
        counts = {s: sum(f.severity == s for f in self.findings) for s in ("error", "silent", "warning", "info")}
        return {"engine": self.engine, "verdict": self.verdict, "counts": counts,
                "findings": [asdict(f) for f in self.findings], "masks": self.masks}


class _Ctx:
    def __init__(self, md: Mdin, engine: str, top: Topology | None, crd: Coordinates | None, policy: bool):
        self.md, self.engine, self.top, self.crd, self.policy = md, engine, top, crd, policy
        self.facts = FACTS[engine]
        self.keys = KEYS.get(engine, {})
        self.out: list[Finding] = []
        self.masks: list[dict] = []
        self.cntrl = md.first("cntrl")

    def add(self, code, severity, message, line=None, namelist=None, key=None, fix=None):
        if severity == "warning" and not self.policy:
            return
        self.out.append(Finding(code, severity, message, line, namelist, key, fix))

    def v(self, key, default=None):
        return self.cntrl.value(key, default) if self.cntrl else default

    def line(self, key):
        e = self.cntrl.get(key) if self.cntrl else None
        return e.line if e else (self.cntrl.line if self.cntrl else None)

    def has(self, key):
        return bool(self.cntrl and self.cntrl.get(key))


def _num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None


# --- structure -------------------------------------------------------------------------------

def _structure(c: _Ctx) -> None:
    md = c.md
    for i in md.issues:
        if i.code == "HIDDEN_NAMELIST":
            name = md.text.split("\n")[i.line - 1].strip().lstrip("&$").split()[0].lower()
            if name.startswith("cntrl"):
                continue   # reported as NO_CNTRL below
            c.add("HIDDEN_NAMELIST", "silent", i.message + f"; &{name} is ignored", i.line,
                  fix="start the line with spaces only, before column 80")
        elif i.code == "NO_TITLE":
            if c.facts["title_optional"]:
                c.add("NO_TITLE", "info", i.message, 1)
            else:
                c.add("NO_TITLE", "error", f"{c.engine} reads line 1 as the title, so a namelist on line 1 is not found",
                      1, fix="put a title line above the first namelist")
        elif i.code == "NO_FINAL_NEWLINE":
            last = md.namelists[-1].name
            if _is_read(c, last):
                c.add(i.code, "error", i.message, i.line, last, fix="end the file with a line break")
        elif i.code == "STRING_SPANS_LINES":
            c.add(i.code, "warning", i.message + "; the engine reads the line break into the value", i.line,
                  fix="keep the string on one line")
        else:
            c.add(i.code, "error", i.message, i.line)
    if c.engine == "sander":
        for nl in md.namelists:
            if nl.after_name not in ("", " "):
                what = "a tab" if nl.after_name == "\t" else repr(nl.after_name)
                if nl.name == "cntrl" and nl is c.cntrl:
                    c.add("NAMELIST_NAME_END", "error", f"&cntrl is followed by {what}: sander finds a namelist only when "
                          "a space or the end of the line follows its name ('Could not find cntrl namelist')", nl.line,
                          "cntrl", fix="put a space or a line break right after &cntrl")
                elif nl.name in c.facts["reads"]:
                    c.add("NAMELIST_NAME_END", "silent", f"&{nl.name} is followed by {what}: sander does not find it, "
                          "so it is ignored", nl.line, nl.name, fix=f"put a space or a line break right after &{nl.name}")
    if c.cntrl is None:
        hidden = [i for i in md.issues if i.code == "HIDDEN_NAMELIST"
                  and md.text.split("\n")[i.line - 1].strip().lstrip("&$").lower().startswith("cntrl")]
        if hidden:
            c.add("NO_CNTRL", "error", f"line {hidden[0].line} starts with a tab, a non-ASCII character, or past column "
                  f"80, so {c.engine} cannot find &cntrl ('Could not find cntrl namelist')", hidden[0].line,
                  fix="start the &cntrl line with spaces only")
        else:
            c.add("NO_CNTRL", "error", "no &cntrl namelist ('Could not find cntrl namelist')", None)
    reads = c.facts["reads"]
    for name in sorted({n.name for n in md.namelists}):
        blocks = md.all(name)
        nl = blocks[0]
        if name in c.facts["rejects_namelists"]:
            c.add("NAMELIST_REJECTED", "error", f"{c.engine} stops when it finds &{name}", nl.line, name,
                  fix=f"remove &{name}")
            continue
        if name not in reads:
            prefix = [r for r in reads if name.startswith(r) and name != r]
            if prefix and (c.engine == "pmemd" or prefix[0] == "cntrl"):
                c.add("NAMELIST_NAME", "error", f"&{name} is read as &{prefix[0]} by the engine's search and then "
                      "fails to parse", nl.line, name, fix=f"spell it &{prefix[0]}")
                continue
            if name in FACTS["amber_namelists"]:
                other = [e for e in ("pmemd", "sander") if e != c.engine and name in FACTS[e]["reads"]]
                why = f"; it is read by {other[0]}" if other else ""
                c.add("NAMELIST_IGNORED", "silent", f"{c.engine} does not read &{name} from mdin{why}", nl.line, name)
            else:
                close = difflib.get_close_matches(name, list(reads), n=1, cutoff=0.6)
                c.add("NAMELIST_UNKNOWN", "silent", f"&{name} is not a namelist {c.engine} reads, so it is ignored",
                      nl.line, name, fix=f"did you mean &{close[0]}?" if close else None)
            continue
        trigger = reads[name]
        if trigger and c.cntrl is not None and not _num(c.v(trigger, 0)):
            c.add("NAMELIST_IGNORED", "silent", f"&{name} is ignored because {trigger}=0", nl.line, name,
                  fix=f"set {trigger}=1 in &cntrl, or remove &{name}")
        if name != "wt" and len(blocks) > 1:
            for extra in blocks[1:]:
                c.add("DUPLICATE_NAMELIST", "silent", f"a second &{name} (line {extra.line}) is ignored; the engine "
                      f"reads only the first (line {nl.line})", extra.line, name, fix="merge them into one")


def _is_read(c: _Ctx, name: str) -> bool:
    """Whether the engine reads this namelist with these &cntrl settings."""
    reads = c.facts["reads"]
    if name not in reads:
        return False
    trigger = reads[name]
    return not trigger or c.cntrl is None or bool(_num(c.v(trigger, 0)))


def _keys(c: _Ctx) -> None:
    for nl in c.md.namelists:
        known = c.keys.get(nl.name) if _is_read(c, nl.name) else None
        seen: dict[str, object] = {}
        for e in nl.entries:
            if known is not None and e.key not in known:
                elsewhere = [n for n, ks in c.keys.items() if e.key in ks and n != nl.name]
                other_engine = [x for x in ("pmemd", "sander") if x != c.engine and e.key in KEYS.get(x, {}).get(nl.name, [])]
                close = difflib.get_close_matches(e.key, known, n=3, cutoff=0.75)
                hint = []
                if other_engine:
                    hint.append(f"{other_engine[0]} accepts it")
                if elsewhere:
                    hint.append(f"it belongs in &{elsewhere[0]}")
                if close:
                    hint.append("did you mean " + " or ".join(close) + "?")
                said = "Cannot match namelist object name" if c.engine == "pmemd" else "error in reading namelist"
                c.add("UNKNOWN_KEY", "error", f"{c.engine} does not accept '{e.key}' in &{nl.name} ('{said}')",
                      e.line, nl.name, e.key, fix="; ".join(hint) or None)
            for v in e.values:
                if v.kind == "bad":
                    looks_mask = any(ch in v.raw for ch in ":@") or e.key in MASK_KEYS
                    c.add("BAD_VALUE", "error", f"{e.key} = {v.raw}: not a number, a logical, or a quoted string",
                          v.line, nl.name, e.key, fix="quote it: " + e.key + "='" + v.raw + "'" if looks_mask else None)
                elif v.kind == "logical" and e.key not in MASK_KEYS and nl.name == "cntrl":
                    c.add("BAD_VALUE", "error", f"{e.key} = {v.raw}: &cntrl flags are integers, not logicals",
                          v.line, nl.name, e.key, fix=f"{e.key}=1")
                elif v.kind == "string" and nl.name in ("cntrl", "ewald") and e.key not in MASK_KEYS \
                        and _numeric_key(c, nl.name, e.key) and _looks_number(v.value):
                    c.add("BAD_VALUE", "error", f"{e.key} = {v.raw}: a number in quotes does not read as a number",
                          v.line, nl.name, e.key, fix=f"{e.key}={v.value.strip()}")
            arrays = KEYS.get("arrays", {}).get(nl.name)
            if arrays is not None and e.index is None and len(e.values) > 1 and e.key not in arrays \
                    and e.key in KEYS.get("types", {}).get(nl.name, {}):
                c.add("VALUE_WITHOUT_KEY", "error", f"{e.key} takes one value; got {len(e.values)} "
                      f"({' '.join(v.raw for v in e.values)}). A missing comma or '=' is the usual cause",
                      e.values[1].line, nl.name, e.key)
            if not e.values or all(v.kind == "null" for v in e.values):
                c.add("EMPTY_VALUE", "silent", f"'{e.key} =' has no value, so the engine keeps its default "
                      "(or an earlier value of the same name)",
                      e.line, nl.name, e.key)
            if e.index is None and e.values:
                val = e.values[0].value
                if e.key in seen and seen[e.key] != val and nl.name != "wt":
                    c.add("DUPLICATE_KEY", "silent", f"{e.key} is set twice in &{nl.name}; the engine uses the last "
                          f"value ({e.values[0].raw})", e.line, nl.name, e.key, fix="keep one")
                seen[e.key] = val


def _numeric_key(c: _Ctx, nl: str, key: str) -> bool:
    return key in KEYS.get("types", {}).get(nl, {}) and KEYS["types"][nl][key] == "num"


def _looks_number(s: str) -> bool:
    try:
        float(s.replace("d", "e").replace("D", "e"))
        return True
    except ValueError:
        return False


# --- &cntrl ----------------------------------------------------------------------------------

def _domains(c: _Ctx) -> None:
    if not c.cntrl:
        return
    for key, allowed in c.facts["domains"].items():
        val = c.v(key)
        if c.has(key) and isinstance(val, int) and val not in allowed:
            c.add("VALUE_DOMAIN", "error", f"{c.engine} accepts {key} = {', '.join(map(str, allowed))}; got {val}",
                  c.line(key), "cntrl", key)
    for key in c.facts["nonnegative"]:
        val = _num(c.v(key))
        if val is not None and val < 0:
            c.add("VALUE_DOMAIN", "error", f"{key} must be >= 0; got {val}", c.line(key), "cntrl", key)
    for key in c.facts["positive"]:
        val = _num(c.v(key))
        if val is not None and val < 0:
            c.add("VALUE_DOMAIN", "error", f"{key} must be positive; got {val}", c.line(key), "cntrl", key)


def _effective_ntb(c: _Ctx) -> int:
    ntb = _num(c.v("ntb"))
    if ntb is not None:
        return int(ntb)
    if (_num(c.v("ntp", 0)) or 0) > 0:
        return 2
    if (_num(c.v("igb", 0)) or 0) > 0:
        return 0
    return 1


def _cntrl(c: _Ctx) -> None:
    if not c.cntrl:
        return
    imin = _num(c.v("imin", 0)) or 0
    md_run = imin == 0
    ntx, irest = _num(c.v("ntx", 1)), _num(c.v("irest", 0))
    ntt = _num(c.v("ntt", 0)) or 0
    gamma = _num(c.v("gamma_ln", 0.0)) or 0.0
    ntp = _num(c.v("ntp", 0)) or 0
    igb = _num(c.v("igb", 0)) or 0
    ntb = _effective_ntb(c)
    ntc, ntf = _num(c.v("ntc", 1)) or 1, _num(c.v("ntf", 1)) or 1
    dt = _num(c.v("dt", 0.001))
    nstlim = _num(c.v("nstlim", 1))

    # restart flags
    if irest == 1 and ntx in (1, 2):
        c.add("RESTART", "error", f"irest=1 with ntx={ntx}: a restart needs velocities (ntx=5)", c.line("irest"),
              "cntrl", "irest", fix="ntx=5, or irest=0 for a fresh start")
    if c.engine == "pmemd" and ntx in (2, 4, 6, 7):
        c.add("NTX_LEGACY", "warning", f"ntx={ntx} is legacy; pmemd auto-detects the file type and suggests "
              f"ntx={1 if ntx == 2 else 5}", c.line("ntx"), "cntrl", "ntx")

    # thermostat
    if gamma > 0 and ntt != 3 and not (c.engine == "sander" and 3 <= ntt <= 10):
        c.add("THERMOSTAT", "error", f"gamma_ln={gamma} is set but ntt={ntt}; the engine requires ntt=3 when "
              "gamma_ln > 0", c.line("gamma_ln"), "cntrl", "gamma_ln", fix="ntt=3, or remove gamma_ln")
    if md_run and ntt == 3 and gamma <= 0:
        c.add("THERMOSTAT_OFF", "silent", "ntt=3 (Langevin) with gamma_ln=0" + ("" if c.has("gamma_ln") else
              " (the default)") + ": no friction, so no temperature control", c.line("ntt"), "cntrl", "gamma_ln",
              fix="set gamma_ln, e.g. gamma_ln=2.0")
    if md_run and ntt == 0 and c.has("temp0") and (nstlim or 0) > 0:
        c.add("TEMP0_UNUSED", "warning", "temp0 is set but ntt=0: no thermostat, so temp0 has no effect (NVE)",
              c.line("temp0"), "cntrl", "temp0", fix="ntt=3 with gamma_ln, or remove temp0")
    if md_run and ntt in (2, 3) and _num(c.v("ig", 71277)) != -1:
        c.add("FIXED_SEED", "warning", f"ig={c.v('ig', 71277)}" + ("" if c.has("ig") else " (the default)") +
              f" with ntt={ntt}: every restart repeats the same random stream", c.line("ig"), "cntrl", "ig",
              fix="ig=-1")

    # periodic boundaries and pressure
    if ntp > 0 and ntb != 2:
        c.add("PRESSURE", "error", f"ntp={ntp} needs ntb=2; got ntb={ntb}", c.line("ntp"), "cntrl", "ntp")
    if ntb == 2 and ntp == 0:
        c.add("PRESSURE", "error", "ntb=2 (constant pressure) needs ntp=1 or 2", c.line("ntb"), "cntrl", "ntb")
    if ntp == 3 and not _num(c.v("csurften", 0)):
        c.add("PRESSURE", "error", "ntp=3 needs csurften > 0", c.line("ntp"), "cntrl", "ntp")
    if c.engine == "pmemd" and ntp > 0 and _num(c.v("barostat", 1)) == 2 and md_run:
        mcbar = _num(c.v("mcbarint", 100)) or 100
        if nstlim is not None and mcbar > nstlim:
            c.add("PRESSURE", "error", f"barostat=2 with mcbarint={mcbar} > nstlim={nstlim}", c.line("barostat"),
                  "cntrl", "mcbarint")
    allowed = c.facts.get("barostat_when_ntp")
    if allowed and ntp > 0 and c.has("barostat") and c.v("barostat") not in allowed:
        c.add("VALUE_DOMAIN", "error", f"with ntp>0, {c.engine} accepts barostat = {', '.join(map(str, allowed))}; "
              f"got {c.v('barostat')}", c.line("barostat"), "cntrl", "barostat")
    if md_run and ntp > 0 and ntt == 0:
        c.add("NPT_NO_THERMOSTAT", "warning", "constant pressure (ntp>0) with no thermostat (ntt=0)",
              c.line("ntp"), "cntrl", "ntt")
    if igb > 0 and c.has("ntb") and ntb != 0:
        if c.engine == "sander":
            c.add("GB_PERIODIC", "error", f"igb={igb} (implicit solvent) needs ntb=0; got ntb={ntb}", c.line("igb"),
                  "cntrl", "ntb", fix="ntb=0")
        else:
            c.add("GB_PERIODIC", "silent", f"igb={igb} (implicit solvent) with ntb={ntb} (periodic): pmemd runs with "
                  "both set, sander refuses the combination", c.line("igb"), "cntrl", "ntb", fix="ntb=0")

    # SHAKE and the timestep
    level = {1: 0, 2: 1, 3: 2}
    if ntc in level and ntf in level and level[ntf] > level[ntc]:
        what = "bonds to hydrogen" if ntf == 2 else "all bonds"
        c.add("SHAKE_MISMATCH", "silent", f"ntf={ntf} drops the forces of {what}, but ntc={ntc} does not constrain "
              "them: those bonds have no force at all", c.line("ntf"), "cntrl", "ntf", fix=f"ntf={ntc}, or ntc={ntf}")
    elif ntc == 2 and ntf == 1:
        c.add("SHAKE_MISMATCH", "info", "ntc=2 with ntf=1 computes forces for bonds that SHAKE then constrains; "
              "ntf=2 is the usual pairing", c.line("ntf"), "cntrl", "ntf")
    if md_run and dt is not None:
        if dt <= 0:
            c.add("DT", "silent", f"dt={dt}: the engine runs, " + ("and nothing moves" if dt == 0 else
                  "with time going backwards"), c.line("dt"), "cntrl", "dt", fix="dt=0.002 (with SHAKE)")
        else:
            hmr = c.top.hmr() if c.top else None
            if ntc == 1 and dt > POLICY["dt_max_no_shake"]:
                c.add("DT", "warning", f"dt={dt} ps without SHAKE (ntc=1); above {POLICY['dt_max_no_shake']} ps "
                      "the bonds to hydrogen are not resolved", c.line("dt"), "cntrl", "dt", fix="ntc=2, ntf=2")
            elif ntc >= 2 and dt > POLICY["dt_max_hmr"]:
                c.add("DT", "warning", f"dt={dt} ps is above {POLICY['dt_max_hmr']} ps even with SHAKE and hydrogen "
                      "mass repartitioning", c.line("dt"), "cntrl", "dt")
            elif ntc >= 2 and dt > POLICY["dt_max_shake"] and not hmr:
                why = "the topology has no hydrogen mass repartitioning" if hmr is False else \
                      "unless the topology uses hydrogen mass repartitioning (pass -p to check)"
                c.add("DT", "warning", f"dt={dt} ps with SHAKE: above {POLICY['dt_max_shake']} ps needs hydrogen "
                      f"mass repartitioning; {why}", c.line("dt"), "cntrl", "dt")
    if md_run and nstlim is not None and nstlim <= 0:
        c.add("NSTLIM", "silent", f"nstlim={nstlim}: no MD steps are run", c.line("nstlim"), "cntrl", "nstlim")

    # cutoff
    cut = _num(c.v("cut"))
    if cut is not None and cut == 0 and c.engine == "pmemd":
        c.add("CUT", "silent", "cut=0 is read as 'use the default': pmemd runs with cut=8.0", c.line("cut"),
              "cntrl", "cut", fix="write the cutoff you mean, e.g. cut=9.0")
    if cut is not None and cut > 0 and ntb > 0 and igb == 0 and cut < POLICY["cut_min_pme"]:
        c.add("CUT", "warning", f"cut={cut} Å with PME; below {POLICY['cut_min_pme']} Å the direct-space sum is "
              "truncated early", c.line("cut"), "cntrl", "cut")
    if c.crd and c.crd.box and ntb > 0 and cut and cut > 0:
        a, b, g = c.crd.box[3:6]
        if abs(a - 90) < 1e-3 and abs(b - 90) < 1e-3 and abs(g - 90) < 1e-3:
            half = min(c.crd.box[:3]) / 2
            skin = _ewald_skin(c)
            if cut + skin > half + 0.01:
                c.add("CUT_BOX", "error", f"cut={cut} Å plus the {skin} Å pairlist skin exceeds half the shortest "
                      f"box side ({half:.2f} Å)", c.line("cut"), "cntrl", "cut",
                      fix=f"cut <= {half - skin:.2f}, or a bigger box")

    # topology-dependent
    if c.top is not None:
        if c.top.ifbox > 0 and ntb == 0 and igb == 0:
            c.add("VACUUM_BOX", "silent", "the topology is periodic (a solvated box) but ntb=0 and igb=0: the box is "
                  "simulated in vacuum, with no periodic images", c.line("ntb"), "cntrl", "ntb", fix="ntb=1")
    if ntb > 0 and (c.crd is not None and c.crd.box is None):
        c.add("NO_BOX", "error", "ntb>0 needs box dimensions in the coordinates, and this file has none "
              "('Box parameters not found in inpcrd file')", c.line("ntb"), "cntrl", "ntb",
              fix="ntb=0 (with igb for implicit solvent), or coordinates with a box")

    # output
    if md_run and nstlim and nstlim > 0:
        ntwx = _num(c.v("ntwx", 0)) or 0
        if ntwx > nstlim:
            c.add("OUTPUT", "silent", f"ntwx={ntwx} > nstlim={nstlim}: no trajectory frame is written",
                  c.line("ntwx"), "cntrl", "ntwx")
        ntpr = _num(c.v("ntpr", 50)) or 50
        if ntpr > nstlim:
            c.add("OUTPUT", "info", f"ntpr={ntpr} > nstlim={nstlim}: only the step-0 energies are printed",
                  c.line("ntpr"), "cntrl", "ntpr")

    # restraints and belly
    ntr = _num(c.v("ntr", 0)) or 0
    ibelly = _num(c.v("ibelly", 0)) or 0
    if c.has("restraintmask") and ntr == 0:
        c.add("MASK_IGNORED", "silent", "restraintmask is set but ntr=0, so nothing is restrained",
              c.line("restraintmask"), "cntrl", "restraintmask", fix="ntr=1")
    if c.has("bellymask") and ibelly == 0:
        c.add("MASK_IGNORED", "silent", "bellymask is set but ibelly=0, so it is ignored",
              c.line("bellymask"), "cntrl", "bellymask", fix="ibelly=1")
    if ntr == 1:
        if not c.has("restraintmask") and not c.md.other_lines:
            c.add("GROUP_INPUT", "error", "ntr=1 with no restraintmask and no group input after the namelists: "
                  "the engine reads past the end of the file", c.line("ntr"), "cntrl", "ntr",
                  fix="restraintmask=':1-100@CA' (your selection) with restraint_wt")
        if (_num(c.v("restraint_wt", 0.0)) or 0.0) <= 0 and c.has("restraintmask"):
            c.add("RESTRAINT_WEIGHT", "silent", "ntr=1 with restraint_wt=0" + ("" if c.has("restraint_wt") else
                  " (the default)") + ": the restraint has no force", c.line("ntr"), "cntrl", "restraint_wt",
                  fix="restraint_wt=10.0 (kcal/mol/Å²; your choice)")
    if ibelly == 1:
        if not c.has("bellymask") and not c.md.other_lines:
            c.add("GROUP_INPUT", "error", "ibelly=1 with no bellymask and no group input after the namelists",
                  c.line("ibelly"), "cntrl", "ibelly")
        if c.has("bellymask"):
            c.add("BELLY", "info", "bellymask selects the atoms that MOVE; everything else is frozen",
                  c.line("bellymask"), "cntrl", "bellymask")
        if c.engine == "pmemd" and ntt == 3:
            c.add("BELLY", "error", "ibelly=1 with ntt=3 is not a valid option in pmemd", c.line("ibelly"),
                  "cntrl", "ibelly")

    # minimization-only / MD-only settings
    if imin == 1:
        ignored = [k for k in ("dt", "nstlim", "ntt", "temp0", "tempi", "gamma_ln") if c.has(k)]
        if ignored:
            c.add("IGNORED_IN_MIN", "info", "imin=1 (minimization) ignores " + ", ".join(ignored), c.cntrl.line,
                  "cntrl")


def _ewald_skin(c: _Ctx) -> float:
    """The pairlist skin the box check uses: skinnb when set, else what each engine was seen to use
    (pmemd 1.0 Å, sander 2.0 Å, by bisecting the largest cut each accepts in a known box)."""
    ew = c.md.first("ewald")
    default = 1.0 if c.engine == "pmemd" else 2.0
    skin = ew.value("skinnb", default) if ew else default
    return float(skin) if isinstance(skin, (int, float)) else default


# --- &wt ---------------------------------------------------------------------------------------

def _wt(c: _Ctx) -> None:
    blocks = c.md.all("wt")
    nmropt = _num(c.v("nmropt", 0)) or 0
    types = c.facts["wt_types"]
    if nmropt > 0:
        if not any(str(b.value("type", "")).strip().upper() == "END" for b in blocks):
            c.add("WT_END", "error", "nmropt>0 needs a closing &wt type='END' / ('No \"wt\" namelist with "
                  "TYPE=END found')", c.line("nmropt"), "cntrl", "nmropt", fix="add the line: &wt type='END' /")
    for b in blocks:
        t = b.value("type")
        if isinstance(t, str) and t.strip().upper() not in types:
            close = difflib.get_close_matches(t.strip().upper(), types, n=1, cutoff=0.6)
            c.add("WT_TYPE", "error", f"&wt type='{t}' is not a type {c.engine} accepts ('Invalid TYPE flag')",
                  b.line, "wt", "type", fix=f"did you mean '{close[0]}'?" if close else None)
    if nmropt == 0 or not c.cntrl:
        return
    nstlim = _num(c.v("nstlim", 1))
    temp0 = _num(c.v("temp0", 300.0))
    ramps = [b for b in blocks if str(b.value("type", "")).strip().upper() == "TEMP0"]
    for b in ramps:
        istep2 = _num(b.value("istep2", 0))
        if nstlim and istep2 and istep2 > nstlim and (_num(c.v("imin", 0)) or 0) == 0:
            c.add("WT_RAMP", "silent", f"the TEMP0 ramp ends at istep2={istep2}, after the run ends "
                  f"(nstlim={nstlim}): it never reaches value2", b.line, "wt", "istep2")
    if ramps:
        last = max(ramps, key=lambda b: _num(b.value("istep2", 0)) or 0)
        v2 = _num(last.value("value2"))
        if v2 is not None and temp0 is not None and abs(v2 - temp0) > 1e-6:
            c.add("WT_RAMP", "warning", f"the TEMP0 ramp ends at value2={v2} but temp0={temp0}: after istep2 the "
                  f"target reverts to the &cntrl temp0, a jump of {abs(v2 - temp0):g} K", last.line, "wt", "value2",
                  fix="make value2 equal temp0")


# --- masks -------------------------------------------------------------------------------------

def _masks(c: _Ctx) -> None:
    limit = c.facts["mask_max_length"]
    for nl in c.md.namelists:
        for e in nl.entries:
            if e.key not in MASK_KEYS or not e.values or e.values[0].kind != "string":
                continue
            m = e.values[0].value
            where = dict(line=e.line, namelist=nl.name, key=e.key)
            if len(m) > limit:
                c.add("MASK_LENGTH", "error", f"{e.key} is {len(m)} characters; {c.engine} reads at most {limit}",
                      **where, fix="shorten it with ranges (':1-50') or wildcards ('@H=')")
                continue
            try:
                maskmod.check_syntax(m)
                if c.top is None:
                    maskmod._tokens(m)
            except maskmod.MaskError as err:
                c.add("MASK_SYNTAX", "error", f"{e.key}='{m}': {err}", **where)
                continue
            except maskmod.Unsupported as err:
                c.add("MASK_UNCHECKED", "silent", f"{e.key}='{m}': {err}", **where)
                continue
            if maskmod.juxtaposed(m):
                c.add("MASK_JUXTAPOSED", "silent", f"{e.key}='{m}': two selections meet with no operator between "
                      "them, and pmemd keeps only the last one", **where,
                      fix="join them with '&' (both) or '|' (either), e.g. '(:1-10)&@CA'")
            for items, what in _lists(m):
                if any(any(ch.isalpha() for ch in x) for x in items) and any(x.strip().isdigit() or
                                                                             "-" in x and x.replace("-", "").isdigit()
                                                                             for x in items):
                    c.add("MASK_MIXED_LIST", "silent", f"{e.key}='{m}': a list mixing numbers and names is read as "
                          f"all names, so the {what} numbers select nothing", **where,
                          fix="split it: ':1|:ALA' instead of ':1,ALA'")
            if c.top is not None:
                _mask_on_topology(c, e.key, m, where)


def _lists(m: str):
    import re
    for sig, what in ((":", "residue"), ("@", "atom")):
        for x in re.finditer(re.escape(sig) + r"(?!%)([^&|!()<>:@]+)", m.replace(" ", "")):
            yield x.group(1).split(","), what


def _mask_on_topology(c: _Ctx, key: str, m: str, where: dict) -> None:
    top = c.top
    try:
        sel = maskmod.select(m, top, c.crd)
    except maskmod.MaskError as err:
        c.add("MASK_SYNTAX", "error", f"{key}='{m}': {err}", **where)
        return
    except maskmod.Unsupported as err:
        c.add("MASK_UNCHECKED", "info", f"{key}='{m}': not evaluated ({err})", **where)
        return
    kinds: dict[str, int] = {}
    for a in sel:
        k = top.kind(top.atom_res[a])
        kinds[k] = kinds.get(k, 0) + 1
    res = sorted({top.atom_res[a] for a in sel})
    c.masks.append({"key": key, "mask": m, "atoms": len(sel), "residues": len(res), "by_kind": kinds,
                    "first_residues": [f"{top.res_labels[r]}{r + 1}" for r in res[:8]]})
    if not sel:
        c.add("MASK_EMPTY", "silent", f"{key}='{m}' selects 0 atoms in this topology", **where)
    import re
    names_res = {n.upper() for n in top.res_labels}
    names_atom = {n.upper() for n in top.atom_names}
    for items, what in _lists(m):
        if not any(any(ch.isalpha() for ch in x) for x in items):
            continue
        pool = names_res if what == "residue" else names_atom
        for x in items:
            x = x.strip()
            if not x or x == "*" or x.endswith("="):
                continue
            if x.upper() not in pool:
                hint = _name_hint(x, pool, what)
                c.add("MASK_NAME", "silent", f"{key}='{m}': no {what} is named '{x}' in this topology", **where,
                      fix=hint)
    if re.search(r"@H(?![A-Za-z0-9=])", m.replace(" ", "")) and any(n.startswith("H") and n != "H" for n in names_atom):
        c.add("MASK_H", "warning", f"{key}='{m}': '@H' matches only atoms named exactly H, not every hydrogen",
              **where, fix="'@H=' matches every name starting with H")
    if key in ("restraintmask",) and (kinds.get("water") or kinds.get("ion")) and kinds.get("protein"):
        c.add("MASK_SOLVENT", "warning", f"{key}='{m}' also restrains {kinds.get('water', 0)} water and "
              f"{kinds.get('ion', 0)} ion atoms", **where, fix="limit it to the solute, e.g. ':1-N@CA'")
    if re.search(r"@CA\b", m) and any(top.kind(r) == "ion" and top.res_labels[r].upper().startswith("CA")
                                       for r in range(top.nres)):
        c.add("MASK_CALCIUM", "warning", f"{key}='{m}': '@CA' also matches calcium ions named CA", **where)


def _name_hint(x: str, pool: set[str], what: str) -> str | None:
    aliases = {"HOH": "WAT", "TIP3": "WAT", "SOL": "WAT", "HIS": "HIE/HID/HIP", "NA": "Na+", "CL": "Cl-", "K": "K+",
               "SOD": "Na+", "CLA": "Cl-", "POT": "K+"}
    a = aliases.get(x.upper())
    if a:
        hits = [y for y in a.upper().split("/") if y in pool]
        if hits:
            return f"this topology calls it {', '.join(hits)}"
    close = difflib.get_close_matches(x.upper(), sorted(pool), n=3, cutoff=0.6)
    return f"close names here: {', '.join(close)}" if close else None


def check_text(text: str, engine: str = "pmemd", top: Topology | None = None, crd: Coordinates | None = None,
               policy: bool = True) -> Report:
    if engine not in ("pmemd", "sander"):
        raise ValueError("engine must be pmemd or sander")
    c = _Ctx(parse(text), engine, top, crd, policy)
    for step in (_structure, _keys, _domains, _cntrl, _wt, _masks):
        step(c)
    order = {"error": 0, "silent": 1, "warning": 2, "info": 3}
    c.out.sort(key=lambda f: (order[f.severity], f.line or 0))
    return Report(engine, c.out, c.masks)
