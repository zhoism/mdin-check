---
name: mdin-check
description: Check an Amber sander/pmemd input file (mdin) before running it. Use after writing or editing any .in/mdin file, before submitting an MD job, or when a run failed with a namelist, mask or "input errors" message. Reports what the engine will refuse, what it will silently ignore or misread, and what each atom mask selects.
---

# mdin-check

Run it on every mdin you write or change, before the job runs:

```bash
mdin-check prod.in --json                                  # syntax, names, values, combinations
mdin-check prod.in -p system.parm7 -c system.rst7 --json   # also masks, box size, HMR
mdin-check prod.in -p system.parm7 -c system.rst7 --run    # also ask the installed engine
```

Add `--engine sander` for sander inputs (the default is pmemd).

Read the JSON:

- `verdict`: `reject` (the engine will refuse it), `suspect` (it will run, but something written is ignored or
  means something else), `ok`.
- `findings[]`: `severity` (error, silent, warning, info), `code`, `message`, `line`, `fix`.
- `masks[]`: for each mask, the number of atoms and residues it selects and their kinds (protein, water, ion,
  other). Compare these with what the mask was meant to select; a mask can be valid and still select the
  wrong atoms.

Exit status: 0 nothing wrong, 1 an error or silent finding, 2 could not check.

Fix every `error` and `silent` finding before running. For a `warning`, either change the setting or keep it
on purpose and say so. Do not edit a value only to make a finding go away: the `fix` field says what the
engine needs, and the value you choose is still a science decision.
