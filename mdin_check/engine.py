"""Ask the engine itself: does pmemd (or sander) accept this input, and what did it read?

The engine reads and validates every namelist before it prints its "4.  RESULTS" header.
The run is killed at that header, so no dynamics happen and a check takes well under a
second. This is the ground truth the static checks are tested against.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

# The header line itself, not the phrase: a title reading "4.  RESULTS" is echoed too.
_READY = re.compile(r"^-+\n   4\.  RESULTS\s*\n-+$", re.M)
_ERROR = re.compile(r"rror|ERROR|BOMB|nvalid|Cannot match|must be|not supported|unsupported", re.I)


@dataclass
class EngineResult:
    accepted: bool
    error: str          # the engine's first error line, "" when accepted
    control: str        # mdout's CONTROL DATA section ("" when rejected): what the engine read
    log: str            # full mdout + stdout, for anything else a caller wants to grep
    timed_out: bool = False   # killed at the timeout before reaching the header: no verdict


def find(engine: str = "pmemd") -> str | None:
    """Path to an engine binary: $MDIN_CHECK_<ENGINE>, then $AMBERHOME/bin, then PATH."""
    env = os.environ.get(f"MDIN_CHECK_{engine.upper()}")
    if env:
        return env
    home = os.environ.get("AMBERHOME")
    if home and (Path(home) / "bin" / engine).exists():
        return str(Path(home) / "bin" / engine)
    return shutil.which(engine)


def _past_echo(log: str, text: str) -> str:
    """mdout after the engine's echo of the input file, so a title can't fake the header."""
    i = log.find("Here is the input file:")
    if i < 0:
        return ""
    return "\n".join(log[i:].split("\n")[2 + len(text.splitlines()):])


def run(text: str, prmtop: str | Path, inpcrd: str | Path, engine: str = "pmemd",
        ref: str | Path | None = None, timeout: float = 60.0, extra_files: dict[str, str] | None = None
        ) -> EngineResult:
    """Run the engine on mdin `text` up to its RESULTS header and report what happened.

    extra_files maps a file name to its contents, written next to the mdin (DISANG= restraint
    files, group input files and the like).
    """
    exe = find(engine)
    if not exe:
        raise FileNotFoundError(f"{engine} not found: set MDIN_CHECK_{engine.upper()} or AMBERHOME, or put it on PATH")
    prmtop, inpcrd = Path(prmtop).resolve(), Path(inpcrd).resolve()
    ref = Path(ref).resolve() if ref else inpcrd
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d)
        (dp / "mdin").write_text(text)
        for name, body in (extra_files or {}).items():
            (dp / name).write_text(body)
        mdout, stdout = dp / "mdout", dp / "stdout"
        with stdout.open("w") as so:
            proc = subprocess.Popen(
                [exe, "-O", "-i", "mdin", "-p", str(prmtop), "-c", str(inpcrd), "-ref", str(ref),
                 "-o", "mdout", "-r", "restrt", "-x", "mdcrd", "-inf", "mdinfo"],
                cwd=d, stdout=so, stderr=subprocess.STDOUT,
                # gfortran buffers mdout; a healthy run can sit on the header for minutes
                env={**os.environ, "GFORTRAN_UNBUFFERED_ALL": "y"},
            )
            deadline = time.time() + timeout
            while proc.poll() is None and time.time() < deadline:
                if mdout.exists() and _READY.search(_past_echo(mdout.read_text(errors="replace"), text)):
                    break
                time.sleep(0.02)
            timed_out = proc.poll() is None
            if timed_out:
                proc.kill()
            proc.wait()
        log = mdout.read_text(errors="replace") if mdout.exists() else ""
        out = stdout.read_text(errors="replace")
    past = _past_echo(log, text)
    m = _READY.search(past)
    if m:
        start = past.find("2.  CONTROL  DATA  FOR  THE  RUN")
        return EngineResult(True, "", past[start:m.start()] if start >= 0 else "", log + "\n" + out)
    if timed_out:
        return EngineResult(False, f"timed out after {timeout:g} s", "", log + "\n" + out, True)
    # search after the echo of the input, so a comment in the mdin that says "must be" is not taken for an error
    body = past if past else log
    lines = [l.strip() for l in (body + "\n" + out).splitlines() if l.strip()]
    errors = [l for l in lines if _ERROR.search(l)]
    return EngineResult(False, (errors[0] if errors else lines[-1] if lines else "no output")[:300], "", log + "\n" + out)
