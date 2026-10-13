"""Collect real mdin files from public GitHub repositories, for testing mdin-check against reality.

    python tools/fetch_corpus.py [--max 2000] [--out corpus]

Uses `gh api` (GitHub code search, then the contents API). Writes corpus/<sha1>.in plus
corpus/manifest.json (repo, path, blob sha, url for each file). The files keep their
authors' licenses, so the corpus is not committed; the manifest says where each came from.
Identical contents are kept once.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

QUERIES = [
    '"&cntrl" imin extension:in', '"&cntrl" imin extension:mdin', '"&cntrl" extension:inp',
    '"&cntrl" ntt extension:in', '"&cntrl" igb extension:in', '"&cntrl" nmropt extension:in',
    '"&cntrl" restraintmask', '"&cntrl" ntr=1', '"&cntrl" ntb=2 ntp', '"&cntrl" irest=1 ntx=5',
    '"&cntrl" gamma_ln', '"&cntrl" maxcyc', '"&wt" "&cntrl"', '"&ewald" "&cntrl"', '"&cntrl" icfe',
    '"&cntrl" igamd', '"&cntrl" filename:heat.in', '"&cntrl" filename:prod.in', '"&cntrl" filename:md.in',
    '"&cntrl" filename:min.in', '"&cntrl" filename:equil.in', '"&cntrl" filename:npt.in', '"&cntrl" filename:nvt.in',
    '"&cntrl" filename:mdin', '"&cntrl" pmemd', '"&cntrl" sander', '"&cntrl" bellymask', '"&cntrl" ntwprt',
    '"&cntrl" iwrap', '"&cntrl" ioutfm', '"&cntrl" barostat', '"&cntrl" "$end"', '"&cntrl" "&end"',
]


def gh(args: list[str]) -> dict | None:
    for attempt in range(5):
        p = subprocess.run(["gh", "api", *args], capture_output=True, text=True)
        if p.returncode == 0:
            return json.loads(p.stdout)
        if "rate limit" in p.stderr.lower() or "403" in p.stderr or "429" in p.stderr:
            time.sleep(30 * (attempt + 1))
            continue
        return None
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=2000)
    ap.add_argument("--out", default="corpus")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(exist_ok=True)
    man_path = out / "manifest.json"
    manifest = json.loads(man_path.read_text()) if man_path.exists() else {}
    seen_blobs = {m["blob"] for m in manifest.values()}
    for q in QUERIES:
        for page in range(1, 11):
            if len(manifest) >= a.max:
                break
            res = gh(["-X", "GET", "search/code", "-f", f"q={q}", "-f", "per_page=100", "-f", f"page={page}"])
            time.sleep(7)   # the code search limit is about 10 requests a minute
            if not res or not res.get("items"):
                break
            for it in res["items"]:
                if it["sha"] in seen_blobs or len(manifest) >= a.max:
                    continue
                seen_blobs.add(it["sha"])
                repo = it["repository"]["full_name"]
                blob = gh([f"repos/{repo}/git/blobs/{it['sha']}"])
                if not blob or blob.get("encoding") != "base64" or blob.get("size", 0) > 200_000:
                    continue
                raw = base64.b64decode(blob["content"])
                text = raw.decode("utf-8", errors="replace")
                if "&cntrl" not in text.lower() and "$cntrl" not in text.lower():
                    continue
                h = hashlib.sha1(raw).hexdigest()
                if h in manifest:
                    continue
                (out / f"{h}.in").write_bytes(raw)
                manifest[h] = {"repo": repo, "path": it["path"], "blob": it["sha"], "url": it["html_url"]}
            man_path.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
            print(f"{q!r} page {page}: {len(manifest)} files", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
