"""Collect the mdin inputs from the official Amber tutorials (https://ambermd.org/tutorials/).

    python tools/fetch_tutorials.py [--out heldout/tutorials] [--max-pages 600]

Crawls the tutorial pages, keeps every linked input file that holds a &cntrl namelist, and
cuts the inputs out of the pages' <pre> blocks (a title line, then the namelists, up to the
next blank-line gap). The files keep their authors' license and are not committed; the
manifest says where each came from.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = "https://ambermd.org/tutorials/"
INPUT_EXT = re.compile(r"\.(in|mdin|inp|txt|i)$", re.I)


def get(url: str) -> str | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "mdin-check corpus fetch"})
        with urllib.request.urlopen(req, timeout=30) as r:
            if r.status != 200:
                return None
            return r.read().decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - a dead link is skipped
        return None


def blocks_from_html(page: str) -> list[str]:
    out = []
    for pre in re.findall(r"<pre[^>]*>(.*?)</pre>", page, re.S | re.I):
        text = html.unescape(re.sub(r"<[^>]+>", "", pre))
        if not re.search(r"[&$]cntrl", text, re.I):
            continue
        lines = text.replace("\r", "").split("\n")
        # an input starts at the line before &cntrl (its title) and runs to the end of the block
        start = next((i for i, l in enumerate(lines) if re.match(r"\s*[&$]cntrl", l, re.I)), None)
        if start is None:
            continue
        out.append("\n".join(lines[max(start - 1, 0):]).strip("\n") + "\n")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="heldout/tutorials")
    ap.add_argument("--max-pages", type=int, default=600)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest: dict = {}
    seen, queue = set(), [ROOT]
    pages = 0
    while queue and pages < a.max_pages:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        body = get(url)
        time.sleep(0.2)
        if body is None:
            continue
        pages += 1
        found: list[str] = []
        is_html = re.search(r"<(html|head|body|!doctype|table|div|p)\b", body[:5000], re.I) is not None
        if not is_html:
            if re.search(r"[&$]cntrl", body, re.I):
                found.append(body)
        else:
            found += blocks_from_html(body)
            for href in re.findall(r'href="([^"#]+)"', body, re.I):
                nxt = urllib.parse.urljoin(url, href)
                if nxt.startswith(ROOT) and nxt not in seen:
                    path = urllib.parse.urlparse(nxt).path
                    if path.endswith((".html", ".htm", ".php", "/")) or INPUT_EXT.search(path):
                        queue.append(nxt)
        for text in found:
            h = hashlib.sha1(text.encode()).hexdigest()
            if h not in manifest:
                (out / f"{h}.in").write_text(text)
                tut = urllib.parse.urlparse(url).path.split("/tutorials/")[-1].split("/")[0]
                manifest[h] = {"repo": f"tutorial:{tut}", "path": url, "blob": h, "url": url}
        if pages % 25 == 0:
            print(f"{pages} pages, {len(manifest)} inputs", flush=True)
            (out / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    print(f"{pages} pages, {len(manifest)} inputs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
