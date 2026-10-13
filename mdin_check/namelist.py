"""Read an mdin file the way sander and pmemd do.

The engines find a namelist by its first line: the first non-blank character is '&' or '$',
followed by the name, within the first 80 columns. A tab or a non-ASCII space counts as
non-blank, so a namelist whose line starts with one is not found. The namelist itself is
then read by gfortran's namelist reader: '!' starts a comment, '/', '&end' or '$end' ends the
group, strings are quoted, repeated keys keep the last value, and the group can span lines.

Every value keeps its line number so a finding can point at it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_NUM = re.compile(r"[+-]?(\d+\.?\d*|\.\d+)([eEdD][+-]?\d+)?$")
_INT = re.compile(r"[+-]?\d+$")
_LOGICAL = re.compile(r"\.?(t|f|true|false)\.?$", re.I)
_KEY = re.compile(r"([A-Za-z][A-Za-z0-9_]*)\s*(\([^)]*\))?\s*(%\s*[A-Za-z_][A-Za-z0-9_]*)?\s*=")
_START = re.compile(r"[&$]([A-Za-z][A-Za-z0-9_]*)")


@dataclass
class Value:
    raw: str
    kind: str          # int | real | logical | string | null | bad
    value: Any
    line: int


@dataclass
class Entry:
    key: str           # lower case, without any (index)
    index: str | None  # the "(...)" after the name, if any
    values: list[Value]
    line: int

    @property
    def first(self) -> Value | None:
        return self.values[0] if self.values else None


@dataclass
class Namelist:
    name: str          # lower case
    line: int
    end_line: int | None
    terminator: str | None   # "/", "&end", "$end", "$", or None when the file ends first
    entries: list[Entry] = field(default_factory=list)
    end_pos: int = 0         # offset just past the terminator
    after_name: str = ""     # the character right after the name on its line ("" at the end of the line)

    def get(self, key: str) -> Entry | None:
        """The entry the engine uses for key: the last one, since a repeated key keeps the last value."""
        hits = [e for e in self.entries if e.key == key and e.index is None]
        return hits[-1] if hits else None

    def value(self, key: str, default: Any = None) -> Any:
        e = self.get(key)
        if e is None or not e.values or e.values[0].kind in ("null", "bad"):
            return default
        return e.values[0].value


@dataclass
class Issue:
    code: str
    message: str
    line: int


@dataclass
class Mdin:
    text: str
    title: str
    namelists: list[Namelist]
    issues: list[Issue]
    other_lines: list[tuple[int, str]]   # non-blank lines outside every namelist, after the title

    def all(self, name: str) -> list[Namelist]:
        return [n for n in self.namelists if n.name == name]

    def first(self, name: str) -> Namelist | None:
        """The block the engine reads: it searches from the top and takes the first match."""
        hits = self.all(name)
        return hits[0] if hits else None


def _value(tok: str, line: int) -> Value:
    if _INT.match(tok):
        return Value(tok, "int", int(tok), line)
    if _NUM.match(tok):
        return Value(tok, "real", float(re.sub(r"[dD]", "e", tok)), line)
    if _LOGICAL.match(tok):
        return Value(tok, "logical", tok.strip(".").lower().startswith("t"), line)
    m = re.match(r"(\d+)\*(.*)$", tok)
    if m:
        inner = _value(m.group(2), line) if m.group(2) else Value("", "null", None, line)
        return Value(tok, inner.kind, inner.value, line)
    return Value(tok, "bad", tok, line)


class _Reader:
    def __init__(self, text: str):
        self.text = text
        self.i = 0
        self.line = 1

    def peek(self, n: int = 1) -> str:
        return self.text[self.i:self.i + n]

    def advance(self, n: int = 1) -> None:
        for _ in range(n):
            if self.i < len(self.text) and self.text[self.i] == "\n":
                self.line += 1
            self.i += 1

    def at_end(self) -> bool:
        return self.i >= len(self.text)


def _start_of_namelist(line: str) -> str | None:
    """The namelist name if this line starts one in the engines' sense, else None."""
    s = line[:80].lstrip(" ")
    m = _START.match(s)
    return m.group(1).lower() if m else None


def _read_group(r: _Reader, nl: Namelist, issues: list[Issue]) -> None:
    """Read the body of a namelist from r (positioned after its name) until its terminator."""
    entry: Entry | None = None
    while not r.at_end():
        c = r.peek()
        if c in " \t\r\n,":
            r.advance()
            continue
        if c == "!":
            while not r.at_end() and r.peek() != "\n":
                r.advance()
            continue
        if c == "/":
            nl.terminator, nl.end_line = "/", r.line
            r.advance()
            return
        rest = r.text[r.i:]
        m = re.match(r"([&$])end\b", rest, re.I)
        if m:
            nl.terminator, nl.end_line = m.group(0).lower(), r.line
            r.advance(len(m.group(0)))
            return
        if c == "$" and not re.match(r"\$\w", rest):
            nl.terminator, nl.end_line = "$", r.line
            r.advance()
            return
        if c in "&$" and re.match(r"[&$][A-Za-z]", rest):
            issues.append(Issue("UNTERMINATED_NAMELIST",
                                f"&{nl.name} (line {nl.line}) is not closed before the next namelist starts", r.line))
            nl.terminator, nl.end_line = None, r.line
            return
        km = _KEY.match(rest)
        if km:
            entry = Entry(km.group(1).lower(), km.group(2), [], r.line)
            nl.entries.append(entry)
            r.advance(len(km.group(0)))
            continue
        if c in "'\"":
            q, start_line, buf = c, r.line, []
            r.advance()
            while not r.at_end():
                if r.peek() == q:
                    if r.peek(2) == q * 2:
                        buf.append(q)
                        r.advance(2)
                        continue
                    r.advance()
                    break
                buf.append(r.peek())
                r.advance()
            else:
                issues.append(Issue("UNCLOSED_QUOTE", f"a {q}-quoted string opened on line {start_line} is never closed",
                                    start_line))
                nl.terminator, nl.end_line = None, r.line
                return
            s = "".join(buf)
            if "\n" in s:
                issues.append(Issue("STRING_SPANS_LINES",
                                    f"a quoted string opened on line {start_line} runs onto line {r.line}", start_line))
            v = Value(q + s + q, "string", s, start_line)
        else:
            j = r.i
            while j < len(r.text) and r.text[j] not in " \t\r\n,/!":
                j += 1
            tok = r.text[r.i:j]
            v = _value(tok, r.line)
            r.advance(j - r.i)
        if entry is None:
            issues.append(Issue("VALUE_WITHOUT_KEY", f"value {v.raw!r} in &{nl.name} has no 'name =' before it", v.line))
        else:
            entry.values.append(v)
    nl.terminator, nl.end_line = None, r.line


_HIDDEN = re.compile(r"^[ \t\u00a0\u2000-\u200b\u3000\ufeff]*[&$][A-Za-z]")


def parse(text: str) -> Mdin:
    issues: list[Issue] = []
    title = text.split("\n", 1)[0]
    namelists: list[Namelist] = []
    other: list[tuple[int, str]] = []
    r = _Reader(text)
    mid_line = False      # True right after a terminator: the rest of that line starts no namelist
    while not r.at_end():
        line_no = r.line
        eol = text.find("\n", r.i)
        eol = len(text) if eol < 0 else eol
        line = text[r.i:eol]
        name = None if mid_line else _start_of_namelist(line)
        mid_line = False
        if name:
            r.advance(len(line) - len(line.lstrip(" ")) + 1 + len(name))
            nl = Namelist(name, line_no, None, None)
            rest = line.lstrip(" ")[1 + len(name):]
            nl.after_name = rest[:1].rstrip("\r")
            _read_group(r, nl, issues)
            nl.end_pos = r.i
            namelists.append(nl)
            mid_line = r.i < len(text) and text[r.i - 1] != "\n"
            continue
        if line.strip() and line_no > 1:
            if _HIDDEN.match(line):
                issues.append(Issue("HIDDEN_NAMELIST",
                                    f"line {line_no} looks like a namelist, but it starts with a tab or a non-ASCII "
                                    "character, so the engine does not see it", line_no))
            other.append((line_no, line))
        r.advance(eol - r.i + 1)
    if namelists and namelists[-1].terminator and "\n" not in text[namelists[-1].end_pos:]:
        issues.append(Issue("NO_FINAL_NEWLINE", f"the file ends right after the closing '{namelists[-1].terminator}' "
                                                "of the last namelist, with no line break; the engine stops with "
                                                "'End of file'", namelists[-1].end_line or 1))
    if namelists and namelists[0].line == 1:
        issues.append(Issue("NO_TITLE", "line 1 is a namelist, not a title. The engine reads line 1 as the title "
                                        "and still finds the namelist, but a title line is expected", 1))
    return Mdin(text, title, namelists, issues, other)
