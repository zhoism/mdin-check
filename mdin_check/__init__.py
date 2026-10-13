"""mdin-check: catch Amber (sander/pmemd) input mistakes before they cost a run."""
from __future__ import annotations

from pathlib import Path

from .rules import Finding, Report, check_text
from .topology import read_coordinates, read_prmtop

__version__ = "0.1.0"
__all__ = ["check", "check_text", "Finding", "Report", "__version__"]


def check(mdin: str | Path, engine: str = "pmemd", prmtop: str | Path | None = None,
          inpcrd: str | Path | None = None, policy: bool = True) -> Report:
    """Check an mdin file. With prmtop (and inpcrd) the masks and box are checked too."""
    top = read_prmtop(prmtop) if prmtop else None
    crd = read_coordinates(inpcrd, top.natom) if inpcrd and top else None
    return check_text(Path(mdin).read_text(errors="replace"), engine, top, crd, policy)
