"""Amber atom masks in the sander/pmemd dialect: parse, evaluate on a topology, explain.

The evaluator reproduces what pmemd 26 selects, including its quirks, and is tested
against pmemd's own "Mask ...; matches N atoms" line (tests/test_mask_vs_pmemd.py):

- spaces are ignored everywhere;
- a list with a letter anywhere in it is read entirely as names (`:1,ALA` drops residue 1);
- two operands with no operator between them keep only the last (`(:1-3)@CA` is `@CA`);
- precedence is () > distance > ! > & > |; `X<:r` takes whole residues, `X<@r` atoms,
  `>` is the complement of `<`, and the reference atoms are inside the cutoff;
- names are case-insensitive and `=` at the end of a name is a prefix wildcard;
- numbers past the end of the system, and reversed ranges, select nothing, without an error.

Anything else the engine rejects raises MaskError with the reason, and anything whose
meaning has not been checked against pmemd raises Unsupported rather than guess.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .topology import Coordinates, Topology


class MaskError(ValueError):
    """pmemd rejects this mask (its run stops with an atommask.f error)."""


class Unsupported(ValueError):
    """Legal, perhaps, but its meaning has not been checked against pmemd."""


@dataclass
class Elem:
    kind: str                  # "res" | "atom" | "type" | "all" | "compound"
    items: list[str]
    atoms: list[str] | None = None      # for compound :res@atom (or @% when atom_type)
    atom_type: bool = False


_DIST = re.compile(r"([<>])([:@])([0-9.eE+-]+)")


def _tokens(mask: str) -> list:
    s = re.sub(r"\s+", "", mask)
    out: list = []
    i = 0
    while i < len(s):
        c = s[i]
        if c in "()!&|":
            out.append(c)
            i += 1
            continue
        if c in "<>":
            m = _DIST.match(s, i)
            if not m and re.match(r"[<>][:@]$", s[i:i + 2]) and (i + 2 == len(s) or s[i + 2] in "()!&|"):
                raise Unsupported("a distance operator with no distance")
            if not m:
                raise MaskError(f"'{c}' must be followed by ':' or '@' and a distance, as in ':1<:5.0'")
            try:
                r = float(m.group(3))
            except ValueError:
                raise MaskError(f"distance {m.group(3)!r} is not a number")
            if r <= 0:
                raise Unsupported("a distance cutoff of zero or less")
            out.append(("dist", m.group(1), m.group(2), r))
            i = m.end()
            continue
        if c == "*":
            out.append(Elem("all", []))
            i += 1
            continue
        if c in ":@":
            j = i + 1
            while j < len(s) and s[j] not in "()!&|<>":
                j += 1
            out.append(_elem(s[i:j]))
            i = j
            continue
        raise MaskError(f"unexpected {c!r} at position {i + 1}; a mask element starts with ':' (residues) or '@' (atoms)")
    return out


def _elem(text: str) -> Elem:
    if text.startswith("@/"):
        raise MaskError("'@/' (element) is cpptraj syntax; pmemd has no element selector. Use names ('@H=') or types ('@%HC')")
    if text.startswith("::"):
        raise MaskError("'::' (chain) is cpptraj syntax; a prmtop has no chains. Use topology residue numbers")
    if text.startswith(":;"):
        raise Unsupported("':;' (original residue number) is cpptraj syntax; pmemd selects nothing with it")
    if "^" in text:
        raise MaskError("'^' (molecule) is cpptraj syntax; pmemd rejects it")
    if text.startswith(":"):
        body = text[1:]
        if ":" in body:
            raise MaskError("':' cannot appear twice in one element; write ':1,3' for a list or ':1|:3' for a union")
        if "@" in body:
            res, at = body.split("@", 1)
            if "@" in at:
                raise Unsupported("two '@' in one element")
            is_type = at.startswith("%")
            return Elem("compound", _items(res, "residue"), _types(at[1:]) if is_type else _items(at, "atom"), is_type)
        return Elem("res", _items(body, "residue"))
    body = text[1:]
    if body.startswith("%"):
        return Elem("type", _types(body[1:]))
    if "@" in body or ":" in body:
        raise MaskError("an '@' list cannot contain ':' or '@'; join two selections with '&' or '|'")
    return Elem("atom", _items(body, "atom"))


def _items(body: str, what: str) -> list[str]:
    if not re.search(r"[A-Za-z]", body) and re.search(r"[^\d,\-*=+]", body):
        raise MaskError(f"{body!r} is not a list of {what} numbers and ranges (digits, ',' and '-' only)")
    if "." in body:
        raise MaskError(f"'.' is not a separator in an Amber mask; use ',' between {what} names and '@' before atoms "
                        "(':1-10@CA,C,N', not ':1-10@CA.C.N')")
    for bad in "*?":
        if bad in body and body != "*":
            raise MaskError(f"'{bad}' is not a wildcard inside a {what} name; Amber's only name wildcard is '=' at the end "
                            "('@H=' is every name starting with H)")
    if "/" in body or "'" in body or '"' in body:
        raise MaskError(f"unexpected character in a {what} list: {body!r}")
    items = [x for x in body.split(",")]
    _name_lengths(items, what)
    return items


def _types(body: str) -> list[str]:
    if any(ch in body for ch in "@%:"):
        raise MaskError("an atom-type list ('@%...') cannot contain '@', '%' or ':'; join two selections with '&'")
    items = _items(body, "type")
    if any("=" in x for x in items):
        raise MaskError("'=' is not a wildcard in an atom-type list ('@%C=' is rejected); list the types")
    return items


def _name_lengths(items: list[str], what: str) -> None:
    """pmemd rejects a name longer than 4 characters, counting a trailing '=' (so ':ABCD=' fails)."""
    if not _is_names(items):
        return
    for x in items:
        if len(x) > 4 and x != "*":
            raise MaskError(f"{what} name {x!r} is longer than 4 characters; Amber names have at most 4 "
                            "(a placeholder left in a template, such as ':1-TOTRES', fails this way)")


def _is_names(items: list[str]) -> bool:
    return any(re.search(r"[A-Za-z]", x) for x in items)


def _name_match(pattern: str, name: str) -> bool:
    p, n = pattern.upper(), name.upper()
    if p == "*":
        return True
    if p.endswith("=") and "=" not in p[:-1]:
        return n.startswith(p[:-1])
    if "=" in p:
        raise Unsupported(f"'=' inside a name ({pattern!r}); pmemd only documents it at the end")
    return n == p


def _numbers(items: list[str], n: int) -> set[int]:
    """1-based numbers and ranges as pmemd reads them: empty pieces are skipped, '1-' is 1."""
    out: set[int] = set()
    for x in items:
        if not x or x == "-":
            continue
        if x == "*":
            out.update(range(1, n + 1))
            continue
        parts = [p for p in x.split("-") if p]
        if not parts:
            continue
        if not all(p.isdigit() for p in parts):
            raise Unsupported(f"number list item {x!r}")
        if len(parts) == 1:
            out.add(int(parts[0]))
        else:
            lo, hi = int(parts[0]), int(parts[-1])
            out.update(range(max(lo, 1), hi + 1))
    return {k for k in out if 1 <= k <= n}


def _res_atoms(top: Topology, residues: set[int]) -> set[int]:
    out: set[int] = set()
    for r in residues:
        end = top.res_start[r + 1] if r + 1 < top.nres else top.natom
        out.update(range(top.res_start[r], end))
    return out


def _select(e: Elem, top: Topology) -> set[int]:
    if e.kind == "all":
        return set(range(top.natom))
    if e.kind in ("res", "compound"):
        if e.items == ["*"]:
            res = set(range(top.nres))
        elif _is_names(e.items):
            res = {r for r in range(top.nres) if any(x and _name_match(x, top.res_labels[r]) for x in e.items)}
        else:
            res = {k - 1 for k in _numbers(e.items, top.nres)}
        atoms = _res_atoms(top, res)
        if e.kind == "res":
            return atoms
        inner = Elem("type" if e.atom_type else "atom", e.atoms or [])
        return atoms & _select(inner, top)
    names = top.atom_types if e.kind == "type" else top.atom_names
    if e.items == ["*"] and e.kind != "type":   # '@%*' selects nothing
        return set(range(top.natom))
    if e.kind == "type":   # no wildcard in a type list: '@%*' selects nothing
        return {a for a in range(top.natom) if any(x and x != "*" and _name_match(x, names[a]) for x in e.items)}
    if _is_names(e.items):
        return {a for a in range(top.natom) if any(x and _name_match(x, names[a]) for x in e.items)}
    return {k - 1 for k in _numbers(e.items, top.natom)}


def _within(ref: set[int], top: Topology, crd: Coordinates, unit: str, r: float) -> set[int]:
    """Atoms within r of any reference atom (the reference atoms included); whole residues for ':'."""
    r2 = r * r
    xyz = crd.xyz
    grid: dict[tuple[int, int, int], list[tuple[float, float, float]]] = {}
    for i in ref:
        p = xyz[i]
        grid.setdefault((math.floor(p[0] / r), math.floor(p[1] / r), math.floor(p[2] / r)), []).append(p)
    near = set(ref)
    for a in range(top.natom):
        if a in near:
            continue
        x, y, z = xyz[a]
        cx, cy, cz = math.floor(x / r), math.floor(y / r), math.floor(z / r)
        hit = False
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for (px, py, pz) in grid.get((cx + dx, cy + dy, cz + dz), ()):
                        if (x - px) ** 2 + (y - py) ** 2 + (z - pz) ** 2 <= r2:
                            hit = True
                            break
                    if hit:
                        break
                if hit:
                    break
            if hit:
                break
        if hit:
            near.add(a)
    if unit == ":":
        near = _res_atoms(top, {top.atom_res[a] for a in near})
    return near


_PREC = {"|": 1, "&": 2, "!": 3}


def select(mask: str, top: Topology, crd: Coordinates | None = None) -> set[int]:
    """0-based indices of the atoms pmemd selects with mask."""
    toks = _tokens(mask)
    if not toks:
        return set()
    if any(isinstance(t, tuple) for t in toks) and crd is None:
        raise Unsupported("a distance mask needs coordinates")
    pos = 0

    def peek():
        return toks[pos] if pos < len(toks) else None

    def take():
        nonlocal pos
        t = toks[pos]
        pos += 1
        return t

    def operand() -> set[int]:
        t = peek()
        if t is None:
            raise MaskError("the mask ends where a selection was expected")
        if t == "!":
            take()
            if peek() == "!":
                raise MaskError("pmemd rejects '!!' at the start of a group and evaluates it wrongly elsewhere; drop both")
            return set(range(top.natom)) - operand()
        if t == "(":
            take()
            v = expr(0)
            if peek() != ")":
                raise MaskError("a '(' is never closed")
            take()
            if v is None:
                raise MaskError("'()' is empty")
        elif isinstance(t, Elem):
            take()
            v = _select(t, top)
        else:
            raise MaskError(f"{t if isinstance(t, str) else t[1] + t[2]!r} where a selection was expected")
        while isinstance(peek(), tuple):
            _, op, unit, r = take()
            inside = _within(v, top, crd, unit, r)
            v = inside if op == "<" else set(range(top.natom)) - inside
        return v

    def expr(min_prec: int) -> set[int] | None:
        if peek() == ")":
            return None
        left = operand()
        while True:
            t = peek()
            if t in ("|", "&"):
                p = _PREC[t]
                if p < min_prec:
                    return left
                take()
                if peek() is None or peek() == ")":
                    raise MaskError(f"'{t}' has nothing after it")
                right = expr(p + 1)
                left = left | right if t == "|" else left & right
            elif t is None or t == ")":
                return left
            else:
                # pmemd keeps the last of two operands with no operator between them
                left = operand()

    v = expr(0)
    if pos < len(toks):
        raise MaskError("a ')' has no matching '('")
    return v if v is not None else set()


def check_syntax(mask: str) -> None:
    """Raise MaskError for a mask pmemd rejects, without needing a topology."""
    toks = _tokens(mask)
    depth, prev = 0, None
    for t in toks:
        if t == "(":
            depth += 1
        elif t == ")":
            depth -= 1
            if depth < 0:
                raise MaskError("a ')' has no matching '('")
            if prev == "(":
                raise MaskError("'()' is empty")
        elif t in ("&", "|"):
            if prev in (None, "(", "&", "|", "!"):
                raise MaskError(f"'{t}' has nothing before it")
        elif t == "!" and prev == "!":
            raise MaskError("pmemd rejects '!!' at the start of a group and evaluates it wrongly elsewhere; drop both")
        prev = t
    if depth > 0:
        raise MaskError("a '(' is never closed")
    if prev in ("&", "|", "!"):
        raise MaskError(f"the mask ends with '{prev}'")


def juxtaposed(mask: str) -> bool:
    """True if two operands meet with no operator between them (pmemd silently keeps the last)."""
    toks = _tokens(mask)
    for a, b in zip(toks, toks[1:]):
        if (a == ")" or isinstance(a, (Elem, tuple))) and (b in ("(", "!") or isinstance(b, Elem)):
            return True
    return False
