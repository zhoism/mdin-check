"""Old-style GROUP input: the lines after the namelists that select atoms for ntr=1 or ibelly=1
when no restraintmask / bellymask is given.

What pmemd 26 and sander do with it, as measured (tests/cases.py, "group" cases):

- the restraint groups come first, then the belly groups; each section ends with a line "END"
  that starts in column 1;
- a group is a title line, a weight line (restraint groups only), then cards, then "END";
- a card starting with ATOM is an atom range, FIND starts filter lines closed by SEARCH, and any
  other word is read as RES;
- the numbers on a card are integer pairs; pmemd reads at most 7 pairs per card, and a lone
  last number is one residue (or atom);
- a residue or atom past the end of the system is clamped, and a reversed range selects nothing;
- lower-case cards, a weight that is not a number, and anything but integers after a card
  stop the engine.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

REDIRECT = re.compile(r"^\s*(DISANG|LISTIN|LISTOUT|DUMPAVE|NOESY|SHIFTS|PCSHIFT|DIPOLE|CSA|RSTAR)\s*=", re.I)
CARD_WORD = re.compile(r"^\s*([A-Za-z]+)")


@dataclass
class Card:
    kind: str            # RES | ATOM | FIND
    pairs: list[tuple[int, int]]
    line: int


@dataclass
class Group:
    title: str
    weight: float | None
    cards: list[Card] = field(default_factory=list)
    line: int = 0


@dataclass
class Problem:
    severity: str        # error | silent
    message: str
    line: int


def lines_of(other_lines: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """The lines that can be group input: everything after the namelists but redirection lines."""
    return [(n, l) for n, l in other_lines if not REDIRECT.match(l)]


def looks_like_groups(lines: list[tuple[int, str]]) -> bool:
    return any(re.match(r"^\s*(RES|ATOM|FIND)\b", l, re.I) for _, l in lines)


def parse(lines: list[tuple[int, str]], sections: list[str], max_pairs: int | None
          ) -> tuple[dict[str, list[Group]], list[Problem]]:
    """sections: the group sections the engine will read, in order ("restraint", "belly")."""
    out: dict[str, list[Group]] = {}
    probs: list[Problem] = []
    i = 0

    def end_of_input(what: str) -> None:
        last = lines[-1][0] if lines else 0
        probs.append(Problem("error", f"the group input ends before {what} ('End of file')", last))

    for sec in sections:
        groups: list[Group] = []
        out[sec] = groups
        while True:
            # skip blank lines between groups
            while i < len(lines) and not lines[i][1].strip():
                i += 1
            if i >= len(lines):
                end_of_input(f"the closing END of the {sec} groups")
                return out, probs
            n, title = lines[i]
            if title.rstrip() == "END":
                i += 1
                break
            if title.strip() == "END":
                probs.append(Problem("error", "the END that closes the group input must start in column 1", n))
                return out, probs
            if title.strip().lower() == "end":
                probs.append(Problem("error", "END must be upper case", n))
                return out, probs
            g = Group(title.strip(), None, line=n)
            groups.append(g)
            i += 1
            if sec == "restraint":
                if i >= len(lines):
                    end_of_input("the weight line")
                    return out, probs
                wn, wl = lines[i]
                tok = wl.split()[0] if wl.split() else ""
                try:
                    g.weight = float(tok.replace("d", "e").replace("D", "e"))
                except ValueError:
                    probs.append(Problem("error", f"restraint group '{g.title}' needs a weight line (a number, the "
                                                  f"force constant) after its title; got {wl.strip()!r}", wn))
                    return out, probs
                i += 1
            while True:
                if i >= len(lines):
                    end_of_input(f"the END of group '{g.title}'")
                    return out, probs
                cn, cl = lines[i]
                i += 1
                if not cl.strip():
                    continue
                if cl.strip() == "END":
                    break
                m = CARD_WORD.match(cl)
                word = m.group(1) if m else ""
                if not word:
                    probs.append(Problem("error", f"a group card must start with RES, ATOM or FIND; got {cl.strip()!r}",
                                         cn))
                    return out, probs
                if word != word.upper():
                    probs.append(Problem("error", f"group cards are upper case ({word.upper()}, not {word})", cn))
                    return out, probs
                if word.startswith("FIND"):
                    while i < len(lines) and lines[i][1].strip().upper() != "SEARCH":
                        i += 1
                    if i >= len(lines):
                        probs.append(Problem("error", "FIND has no SEARCH line closing its filters", cn))
                        return out, probs
                    i += 1
                    g.cards.append(Card("FIND", [], cn))
                    continue
                kind = "ATOM" if word.startswith("ATOM") else "RES"
                if kind == "RES" and not word.startswith("RES"):
                    probs.append(Problem("silent", f"'{word}' is not a group card; the engine reads it as RES", cn))
                rest = cl[m.end():].split()
                if not all(re.fullmatch(r"-?\d+", t) for t in rest):
                    bad = next(t for t in rest if not re.fullmatch(r"-?\d+", t))
                    probs.append(Problem("error", f"{kind} takes integers only; got {bad!r} ('rfree: Error decoding "
                                                  "variable'). A placeholder left in a template fails this way", cn))
                    return out, probs
                nums = [int(t) for t in rest]
                pairs = [(nums[k], nums[k + 1] if k + 1 < len(nums) else nums[k]) for k in range(0, len(nums), 2)]
                if max_pairs and len(pairs) > max_pairs:
                    probs.append(Problem("silent", f"{kind} has {len(pairs)} ranges; pmemd reads only the first "
                                                   f"{max_pairs} on a card", cn))
                    pairs = pairs[:max_pairs]
                g.cards.append(Card(kind, pairs, cn))
    return out, probs


def select(g: Group, top) -> set[int] | None:
    """0-based atoms of a group, or None if it uses FIND (not evaluated)."""
    atoms: set[int] = set()
    for c in g.cards:
        if c.kind == "FIND":
            return None
        for a, b in c.pairs:
            lo, hi = abs(a), b
            if c.kind == "RES":
                for r in range(max(lo, 1), min(hi, top.nres) + 1):
                    end = top.res_start[r] if r < top.nres else top.natom
                    atoms.update(range(top.res_start[r - 1], end))
            else:
                atoms.update(range(max(lo, 1) - 1, min(hi, top.natom)))
    return atoms
