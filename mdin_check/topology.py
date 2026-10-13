"""Read the parts of an Amber prmtop and an ASCII restart that the checks need."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

WATER = {"WAT", "HOH", "TIP3", "TIP4", "TP3", "TP4", "T3P", "T4P", "SOL", "OPC", "SPC", "TIP5", "T5P"}
IONS = {"NA", "NA+", "CL", "CL-", "K", "K+", "MG", "MG2", "CA", "CA2", "ZN", "ZN2", "LI", "LI+", "RB", "RB+", "CS",
        "CS+", "F", "F-", "BR", "BR-", "I", "I-", "SOD", "CLA", "POT", "CAL", "MN", "FE", "FE2", "CU", "CU1", "NI",
        "CD", "HG", "SR", "BA", "AL", "IOD", "CO"}
AMINO = {"ALA", "ARG", "ASN", "ASP", "ASH", "CYS", "CYX", "CYM", "GLN", "GLU", "GLH", "GLY", "HIS", "HID", "HIE",
         "HIP", "HYP", "ILE", "LEU", "LYS", "LYN", "MET", "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL", "ACE",
         "NME", "NHE"}


@dataclass
class Topology:
    path: str
    atom_names: list[str]
    atom_types: list[str]
    masses: list[float]
    atomic_numbers: list[int] | None
    res_labels: list[str]
    res_start: list[int]        # 0-based index of each residue's first atom
    ifbox: int                  # 0 none, 1 orthogonal, 2 truncated octahedron/general
    atom_res: list[int]         # 0-based residue index of each atom

    @property
    def natom(self) -> int:
        return len(self.atom_names)

    @property
    def nres(self) -> int:
        return len(self.res_labels)

    def kind(self, res: int) -> str:
        """protein | water | ion | other, by residue name."""
        name = self.res_labels[res].upper()
        if name in WATER:
            return "water"
        if name in IONS or (name[-1:] in ("+", "-") and name.rstrip("+-") in IONS):
            return "ion"
        if name in AMINO or name[1:] in AMINO and name[0] in "NC":
            return "protein"
        return "other"

    def hmr(self) -> bool:
        """Hydrogen mass repartitioning: some hydrogen is heavier than 2 amu."""
        return any(self._is_h(i) and m > 2.0 for i, m in enumerate(self.masses))

    def _is_h(self, i: int) -> bool:
        if self.atomic_numbers:
            return self.atomic_numbers[i] == 1
        return self.atom_names[i].upper().startswith("H") and self.masses[i] < 4.5


def _sections(text: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    flag, fmt, rows = None, None, []
    for line in text.splitlines():
        if line.startswith("%FLAG"):
            if flag:
                out[flag] = _split(rows, fmt)
            flag, fmt, rows = line.split()[1], None, []
        elif line.startswith("%FORMAT"):
            fmt = line[line.index("(") + 1:line.rindex(")")]
        elif line.startswith("%"):
            continue
        elif flag:
            rows.append(line)
    if flag:
        out[flag] = _split(rows, fmt)
    return out


def _split(rows: list[str], fmt: str | None) -> list[str]:
    m = re.match(r"(\d+)([aAiIeEfF])(\d+)", fmt or "")
    if not m:
        return " ".join(rows).split()
    width = int(m.group(3))
    vals = []
    for row in rows:
        for j in range(0, len(row), width):
            v = row[j:j + width]
            if v.strip() or m.group(2) in "aA":
                vals.append(v.strip() if m.group(2) not in "aA" else v.rstrip())
    return vals


def read_prmtop(path: str | Path) -> Topology:
    s = _sections(Path(path).read_text(errors="replace"))
    ptr = [int(x) for x in s["POINTERS"]]
    natom, nres = ptr[0], ptr[11]
    names = [n.strip() for n in s["ATOM_NAME"][:natom]]
    types = [n.strip() for n in s.get("AMBER_ATOM_TYPE", [""] * natom)[:natom]]
    labels = [n.strip() for n in s["RESIDUE_LABEL"][:nres]]
    starts = [int(x) - 1 for x in s["RESIDUE_POINTER"][:nres]]
    masses = [float(x) for x in s.get("MASS", ["0"] * natom)[:natom]]
    anum = [int(x) for x in s["ATOMIC_NUMBER"][:natom]] if "ATOMIC_NUMBER" in s else None
    atom_res = []
    for r in range(nres):
        end = starts[r + 1] if r + 1 < nres else natom
        atom_res += [r] * (end - starts[r])
    return Topology(str(path), names, types, masses, anum, labels, starts, ptr[27] if len(ptr) > 27 else 0, atom_res)


@dataclass
class Coordinates:
    xyz: list[tuple[float, float, float]]
    box: tuple[float, float, float, float, float, float] | None
    has_velocities: bool


def read_inpcrd(path: str | Path, natom: int) -> Coordinates | None:
    """ASCII restart/inpcrd only; returns None for a NetCDF file."""
    raw = Path(path).read_bytes()
    if raw[:4] in (b"CDF\x01", b"CDF\x02", b"\x89HDF"):
        return None
    lines = raw.decode(errors="replace").splitlines()
    nums: list[float] = []
    for line in lines[2:]:
        for j in range(0, len(line.rstrip()), 12):
            f = line[j:j + 12].strip()
            if f:
                nums.append(float(f))
    xyz = [tuple(nums[3 * i:3 * i + 3]) for i in range(natom)]
    rest = nums[3 * natom:]
    has_vel = len(rest) >= 3 * natom
    if has_vel:
        rest = rest[3 * natom:]
    box = tuple(rest[:6]) if len(rest) >= 6 else (tuple(rest[:3]) + (90.0, 90.0, 90.0) if len(rest) >= 3 else None)
    return Coordinates(xyz, box, has_vel)


_NC_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 4, 6: 8}
_NC_FMT = {1: "b", 2: "c", 3: "h", 4: "i", 5: "f", 6: "d"}


def _netcdf3(raw: bytes) -> dict[str, list]:
    """The non-record variables of a NetCDF-3 file (classic or 64-bit offset), flattened."""
    import struct

    version = raw[3]
    pos = 8   # magic + numrecs

    def i32() -> int:
        nonlocal pos
        v = struct.unpack_from(">i", raw, pos)[0]
        pos += 4
        return v

    def name() -> str:
        nonlocal pos
        n = i32()
        s = raw[pos:pos + n].decode()
        pos += (n + 3) // 4 * 4
        return s

    def skip_atts() -> None:
        nonlocal pos
        i32()
        for _ in range(i32()):
            name()
            t, n = i32(), i32()
            pos += (n * _NC_SIZES[t] + 3) // 4 * 4

    i32()
    dims = []
    for _ in range(i32()):
        dims.append((name(), i32()))
    skip_atts()
    out = {}
    i32()
    for _ in range(i32()):
        vname = name()
        ids = [i32() for _ in range(i32())]
        skip_atts()
        t = i32()
        i32()  # vsize
        begin = struct.unpack_from(">q" if version == 2 else ">i", raw, pos)[0]
        pos += 8 if version == 2 else 4
        if any(dims[d][1] == 0 for d in ids):   # record variable: not in a restart
            continue
        count = 1
        for d in ids:
            count *= dims[d][1]
        out[vname] = list(struct.unpack_from(f">{count}{_NC_FMT[t]}", raw, begin))
    return out


def read_coordinates(path: str | Path, natom: int) -> Coordinates:
    """An Amber restart or inpcrd, ASCII or NetCDF."""
    raw = Path(path).read_bytes()
    if raw[:4] in (b"CDF\x01", b"CDF\x02"):
        v = _netcdf3(raw)
        c = v["coordinates"]
        xyz = [tuple(c[3 * i:3 * i + 3]) for i in range(natom)]
        box = tuple(v["cell_lengths"]) + tuple(v.get("cell_angles", [90.0, 90.0, 90.0])) if "cell_lengths" in v else None
        return Coordinates(xyz, box, "velocities" in v)
    if raw[:4] == b"\x89HDF":
        raise ValueError(f"{path}: NetCDF-4/HDF5 restarts are not supported; convert with cpptraj")
    return read_inpcrd(path, natom)
