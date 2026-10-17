# mdin-check

A checker for Amber `sander` and `pmemd` input files (mdin). It reports three kinds of problem:

- **error**: the engine will refuse the file and stop before the first step.
- **silent**: the engine will run, but something you wrote is ignored or means something else. A
  misspelled `&ewlad`, a `restraintmask` with `ntr=0`, Langevin dynamics with no `gamma_ln`, a mask that
  selects water you meant to leave free.
- **warning**: legal, but outside common practice (a 4 fs step without hydrogen mass repartitioning, a
  fixed random seed with a stochastic thermostat). These are opinions and `--no-policy` drops them.

With the topology it also evaluates every atom mask and says what it selects, the way pmemd would.

It needs only Python 3.9+, no dependencies, and no Amber install. If Amber is installed, `--run` also
asks the engine itself.

pmemd 26 accepts `examples/heat.in` and would run it. mdin-check, given the solvated test system in
`tests/systems/`:

```
$ mdin-check examples/heat.in -p tests/systems/solv.parm7 -c tests/systems/solv.rst7
heat.in (pmemd): SUSPECT - 4 silent, 2 warning
  heat.in:5: silent  THERMOSTAT_OFF: ntt=3 (Langevin) with gamma_ln=0 (the default): no friction, so no temperature control
      fix: set gamma_ln, e.g. gamma_ln=2.0
  heat.in:6: silent  RESTRAINT_WEIGHT: ntr=1 with restraint_wt=0 (the default): the restraint has no force
      fix: restraint_wt=10.0 (kcal/mol/Å²; your choice)
  heat.in:9: silent  WT_RAMP: the TEMP0 ramp ends at istep2=50000, after the run ends (nstlim=25000): it never reaches value2
  heat.in:11: silent  NAMELIST_UNKNOWN: &ewlad is not a namelist pmemd reads, so it is ignored
      fix: did you mean &ewald?
  heat.in:4: warning DT: dt=0.004 ps with SHAKE: above 0.002 ps needs hydrogen mass repartitioning; the topology has no hydrogen mass repartitioning
  heat.in:6: warning MASK_SOLVENT: restraintmask='@CA,C,N,O' also restrains 1486 water and 0 ion atoms
      fix: limit it to the solute, e.g. ':1-N@CA'
  mask restraintmask='@CA,C,N,O': 1526 atoms in 1496 residues (40 protein, 1486 water); first: ALA1 HIE2 CYS3 ASP4 LYS5 GLU6 TRP7 PHE8
```

## Install

```bash
pip install git+https://github.com/zhoism/mdin-check
```

## Use

```bash
mdin-check prod.in                                   # the file alone
mdin-check prod.in -p sys.parm7 -c sys.rst7          # + masks, cutoff vs box, HMR, periodicity
mdin-check prod.in -p sys.parm7 -c sys.rst7 --run    # + run the installed engine to its first step
mdin-check *.in --engine sander --json               # one JSON object per file
```

Exit status: 0 if there is no error or silent finding, 1 if there is, 2 if a file could not be read.
`--strict` also exits 1 on warnings.

From Python:

```python
import mdin_check
report = mdin_check.check("prod.in", engine="pmemd", prmtop="sys.parm7", inpcrd="sys.rst7")
report.verdict          # "reject" | "suspect" | "ok"
report.to_dict()        # findings with code, severity, message, line, fix; mask selections
```

### From an agent

The JSON output is meant for programs. `skill/SKILL.md` is a ready instruction file for Claude Code,
OpenClaw and similar agent frameworks: copy it into the agent's skills directory. The pattern is: write
the mdin, run `mdin-check --json`, fix every `error` and `silent` finding, and compare each mask's
`atoms`/`by_kind` with what the mask was meant to select.

## What the findings rest on

Every `error` and `silent` rule is a claim about what the engine does, so each has a case in
`tests/cases.py` with the engine's recorded verdict. `tests/test_vs_engine.py` runs every case through
the installed pmemd and sander and fails if the engine's behaviour has changed. The tables in
`mdin_check/data/` were measured from the engines, not copied from the manual:

| table | how it was made |
|---|---|
| the names each namelist accepts (`keys.json`) | every identifier in the Amber 2026 manual and in the engine binaries' strings, each written into the namelist and run (`tools/derive_keys.py`) |
| value domains, namelists read, `&wt` types (`engine_facts.json`) | probe inputs; `tests/test_engine_facts.py` re-runs each one |
| mask semantics | `mdin_check/mask.py` is checked against pmemd's own `Mask ...; matches N atoms` count for 630 masks on two systems (`tools/record_mask_counts.py`, `tests/test_mask.py`) |

The tables come from pmemd 26 (CPU build) and sander from AmberTools 24.8. Other versions may
differ; `--run` checks against whatever is installed.

### Against real files

`tools/fetch_corpus.py` collects mdin files from public GitHub repositories and
`tools/eval_corpus.py` runs each one through mdin-check and through pmemd on a test system. A file
that fails only because it needs its own system (TI masks that match its own atoms, a DISANG file,
an MPI build) is counted as "environment" and left out of the score. The results file lists every
file, its repository, the engine's message and mdin-check's findings:

```bash
python tools/fetch_corpus.py --max 2000
python tools/eval_corpus.py corpus --engine pmemd --out results/corpus_pmemd.json
```

Results on 2,000 files from 208 repositories (`results/corpus_pmemd.json`, `results/corpus_sander.json`).
"Agree" means mdin-check reported an error exactly when the engine refused the file; a "miss" would be a
file the engine refused with no error from mdin-check, and a "false alarm" an error on a file the engine
ran. Three repositories supply 1,208 of the files, so the second column counts at most 5 per repository.

| engine | scored | agree | miss | false alarm | scored, max 5 per repo | agree |
|---|---|---|---|---|---|---|
| pmemd 26 | 876 | 876 | 0 | 0 | 432 | 432 |
| sander (AmberTools 24.8) | 1,893 | 1,893 | 0 | 0 | 458 | 458 |

This is agreement on whether the engine refuses a file. It says nothing about the `silent` findings,
which the engine runs by definition; those rest on the cases in `tests/cases.py`. The files that cannot
be scored are left out: 1,123 for pmemd (mostly TI inputs whose masks match their own system) and 105
for sander (QM/MM inputs that need their own system or an external QM program, and the like). Each
"environment" file is matched by a specific engine message, listed in `ENVIRONMENT` in
`tools/eval_corpus.py`.

Running the corpus is how several rules were found: a file that ends right after the closing `/`,
sander missing a namelist when a tab or `!` follows its name, mask names over 4 characters, constant
pH with constant pressure, template placeholders in GROUP input, and where GROUP input has to sit
relative to the namelists (the two engines differ).

### Held out

The rules above were written while looking at the GitHub corpus, so it is not a fair test of them.
Two sets were kept out until the rules were done, and run once:

- 355 mdin files written by language models (Claude Haiku, Claude Sonnet, Gemini, Qwen2.5-7B) for
  ordinary MD tasks, many of them broken in ways people do not break them;
- 206 inputs from the official Amber tutorials (`tools/fetch_tutorials.py`, 36 tutorials).

The first run of each found rules the corpus had not: integer settings written with a decimal point
(`nstlim=1000.0`; `timlim` is an integer in pmemd and a real in sander), `ntr` outside 0/1, pmemd's
`eedmeth`, Langevin with no friction at constant pressure, softcore TI without `icfe=1` or `ntf=1`,
the cutoff floor for GB and vacuum runs (and sander's default `cut` of 8 Å under it), an unclosed
namelist at the end of the file, and that errors inside a namelist the engine skips do not matter.
It also found three faults in the harness: an HTML page scraped as an input, and environment
patterns loose enough to file real misses as "environment". After the fixes:

| set | engine | scored | agree |
|---|---|---|---|
| language models | pmemd | 355 | 355 |
| language models | sander | 355 | 355 |
| Amber tutorials | pmemd | 176 | 176 |
| Amber tutorials | sander | 162 | 162 |

These are second runs, after fixing what the first ones found, so they are no longer held out either.
The first runs are the held-out numbers: on the language-model set pmemd agreed on 345 of 352 scored
files (7 false alarms, all garbage inside a `&wt` the engine skips) and sander on 346 of 353 (6 false
alarms, 1 miss); on the tutorials, pmemd agreed on 171 of 176 (5 misses) once the harness faults were
fixed. The next unseen set is the honest test.

## Limits

- Key names are checked for `&cntrl`, `&ewald`, `&wt` (and `&qmmm` for sander). Other namelists are
  checked for syntax only.
- Old-style GROUP input is parsed and its RES/ATOM groups are evaluated on the topology. Groups that
  use FIND filters are checked for syntax but not evaluated.
- Restarts in NetCDF-4/HDF5 format are not read (pmemd and sander write NetCDF-3, which is).
- pmemd.cuda and pmemd.MPI were not probed. Some options they accept are refused by the CPU build,
  and the reverse.
- A mask is evaluated on the coordinates you pass. Distance masks (`<:`, `<@`) depend on them, as
  they do in pmemd.
- Warnings encode one set of practices (2 fs with SHAKE, 4 fs with HMR, `cut` ≥ 8 Å with PME,
  `ig=-1` with Langevin). The thresholds are in `POLICY` in `mdin_check/rules.py`.
- QM/MM and TI inputs are checked for syntax, names and the common settings; rules that need the
  system's own chemistry (the QM region's charge, TI masks that must match) are not there.

## License

MIT. The derived tables describe the behaviour of the Amber engines and contain no Amber code.
