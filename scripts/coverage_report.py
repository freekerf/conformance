#!/usr/bin/env python3
"""Line/branch coverage of the C# core from an AltCover (OpenCover) report.

Only files/line ranges listed in scope.toml are counted. exclusions.toml lists
lines that are unreachable/untestable in this environment, each with a reason;
the report shows raw coverage and coverage net of those exclusions.

Usage: coverage_report.py <coverage.xml> <out_dir> [--repo REPO] [--fail-under N]

Writes <out_dir>/index.html (+ one page per file) and <out_dir>/summary.json,
and prints a per-file table.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
import tomllib
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def load_scope():
    scope = tomllib.load(open(ROOT / "scope.toml", "rb"))["file"]
    excl_path = ROOT / "exclusions.toml"
    excl = tomllib.load(open(excl_path, "rb")).get("exclusion", []) if excl_path.exists() else []
    return scope, excl


def in_ranges(line: int, ranges) -> bool:
    return not ranges or any(a <= line <= b for a, b in ranges)


def rel_path(full: str) -> str:
    # build copy: .../build/src/LaserGRBL/X.cs -> LaserGRBL/X.cs
    norm = full.replace("\\", "/")
    marker = "/src/LaserGRBL/"
    i = norm.rfind(marker)
    return norm[i + len("/src/"):] if i >= 0 else norm


def collect(xml_path: Path, scope, excl):
    """Visit counts per scope entry. A file may appear in several entries (e.g. part of
    GrblFile.cs is "core", part "importers"): a line belongs to the first entry, in
    scope.toml order, whose ranges contain it. Entries are keyed by their index."""
    tree = ET.parse(xml_path)
    files: dict[str, str] = {}  # uid -> rel path
    for f in tree.iter("File"):
        files[f.get("uid")] = rel_path(f.get("fullPath"))
    by_path = defaultdict(list)
    for i, s in enumerate(scope):
        by_path[s["path"]].append(i)

    def owner(path, ln):
        for i in by_path.get(path, ()):
            if in_ranges(ln, scope[i].get("ranges")):
                return i
        return None

    lines = defaultdict(lambda: defaultdict(int))  # entry -> line -> max vc
    branches = defaultdict(lambda: defaultdict(list))  # entry -> line -> [vc...]
    seen_bp = set()
    for method in tree.iter("Method"):
        fref = method.find("FileRef")
        default_uid = fref.get("uid") if fref is not None else None
        for sp in method.iter("SequencePoint"):
            path = files.get(sp.get("fileid") or default_uid)
            ln = int(sp.get("sl"))
            i = owner(path, ln)
            if i is None:
                continue
            lines[i][ln] = max(lines[i][ln], int(sp.get("vc", "0")))
        for bp in method.iter("BranchPoint"):
            path = files.get(bp.get("fileid") or default_uid)
            ln = int(bp.get("sl"))
            i = owner(path, ln)
            if i is None:
                continue
            key = (path, bp.get("uspid"), method.find("Name").text if method.find("Name") is not None else "")
            if key in seen_bp:
                continue
            seen_bp.add(key)
            branches[i][ln].append(int(bp.get("vc", "0")))

    excluded = defaultdict(dict)  # path -> line -> reason
    for e in excl:
        a, b = e["lines"]
        for ln in range(a, b + 1):
            excluded[e["file"]][ln] = f'[{e.get("category", "other")}] {e["reason"]}'
    return lines, branches, excluded


def pct(c, t):
    return 100.0 * c / t if t else 100.0


def entry_label(scope, i) -> str:
    path = scope[i]["path"]
    dup = sum(1 for s in scope if s["path"] == path) > 1
    return f"{path} [{scope[i].get('tier', 'core')}]" if dup else path


def summarize(scope, lines, branches, excluded):
    rows = []
    for i, spec in enumerate(scope):
        path = spec["path"]
        L = lines.get(i, {})
        B = branches.get(i, {})
        X = excluded.get(path, {})
        lt = len(L)
        lc = sum(1 for v in L.values() if v > 0)
        bt = sum(len(v) for v in B.values())
        bc = sum(1 for v in B.values() for x in v if x > 0)
        nl = {ln: v for ln, v in L.items() if ln not in X}
        nb = {ln: v for ln, v in B.items() if ln not in X}
        nlt, nlc = len(nl), sum(1 for v in nl.values() if v > 0)
        nbt, nbc = sum(len(v) for v in nb.values()), sum(1 for v in nb.values() for x in v if x > 0)
        uncovered = sorted(ln for ln, v in nl.items() if v == 0)
        partial = sorted(ln for ln, v in nb.items() if any(x == 0 for x in v))
        rows.append({
            "file": path, "label": entry_label(scope, i), "entry": i, "tier": spec.get("tier", "core"),
            "ranges": spec.get("ranges"),
            "lines": [lc, lt], "branches": [bc, bt],
            "net_lines": [nlc, nlt], "net_branches": [nbc, nbt],
            "excluded_lines": sum(1 for ln in L if ln in X),
            "uncovered_lines": uncovered, "partial_branch_lines": partial,
        })
    return rows


def ranges_str(nums):
    out, start, prev = [], None, None
    for n in nums:
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            out.append(f"{start}-{prev}" if start != prev else str(start))
            start = prev = n
    if start is not None:
        out.append(f"{start}-{prev}" if start != prev else str(start))
    return ",".join(out)


def print_table(rows):
    hdr = f"{'file':50} {'tier':9} {'lines':>15} {'branches':>15} {'net lines':>10} {'net br.':>10}"
    print(hdr)
    print("-" * len(hdr))
    tot = {}
    for r in rows:
        lc, lt = r["lines"]
        bc, bt = r["branches"]
        nlc, nlt = r["net_lines"]
        nbc, nbt = r["net_branches"]
        t = tot.setdefault(r["tier"], [0] * 8)
        for i, v in enumerate((lc, lt, bc, bt, nlc, nlt, nbc, nbt)):
            t[i] += v
        print(f"{r['label'][-50:]:50} {r['tier']:9} {lc:5}/{lt:<5} {pct(lc, lt):3.0f}% {bc:5}/{bt:<5} {pct(bc, bt):3.0f}%"
              f" {pct(nlc, nlt):9.1f}% {pct(nbc, nbt):9.1f}%")
    print("-" * len(hdr))
    for tier, t in tot.items():
        if t[1]:
            print(f"{'TOTAL ' + tier:50} {'':9} {t[0]:5}/{t[1]:<5} {pct(t[0], t[1]):3.0f}% {t[2]:5}/{t[3]:<5} {pct(t[2], t[3]):3.0f}%"
                  f" {pct(t[4], t[5]):9.1f}% {pct(t[6], t[7]):9.1f}%")
    return tot


def write_html(out: Path, rows, lines, branches, excluded, repo: Path):
    out.mkdir(parents=True, exist_ok=True)
    css = """body{font-family:system-ui,sans-serif;margin:16px;background:#fff;color:#222}
table{border-collapse:collapse}td,th{padding:3px 8px;border-bottom:1px solid #ddd;text-align:right}
td:first-child,th:first-child{text-align:left}.src{font-family:monospace;font-size:12px;white-space:pre}
.src div{padding:0 4px}.hit{background:#dfd}.miss{background:#fcc}.part{background:#ffd}.excl{background:#e4e4f4;color:#666}
.ln{display:inline-block;width:5em;color:#888}.vc{display:inline-block;width:5em;color:#888}
@media (prefers-color-scheme: dark){body{background:#111;color:#ddd}.hit{background:#1d3a1d}.miss{background:#4a1c1c}
.part{background:#40401a}.excl{background:#262640;color:#999}td,th{border-color:#333}}"""
    idx = [f"<!doctype html><meta charset=utf-8><title>LaserGRBL coverage</title><style>{css}</style>",
           "<h1>LaserGRBL coverage (C#)</h1><table><tr><th>file</th><th>tier</th><th>lines</th><th>branches</th>"
           "<th>net lines</th><th>net branches</th><th>excluded lines</th></tr>"]
    for r in rows:
        page = r["file"].replace("/", "_") + (f"_{r['tier']}" if r["label"] != r["file"] else "") + ".html"
        lc, lt = r["lines"]
        bc, bt = r["branches"]
        idx.append(f"<tr><td><a href='{page}'>{html.escape(r['label'])}</a></td><td>{r['tier']}</td>"
                   f"<td>{lc}/{lt} ({pct(lc, lt):.1f}%)</td><td>{bc}/{bt} ({pct(bc, bt):.1f}%)</td>"
                   f"<td>{pct(*r['net_lines']):.1f}%</td><td>{pct(*r['net_branches']):.1f}%</td><td>{r['excluded_lines']}</td></tr>")
        src = (repo / r["file"]).read_text(encoding="utf-8-sig", errors="replace").splitlines()
        L, B, X = lines.get(r["entry"], {}), branches.get(r["entry"], {}), excluded.get(r["file"], {})
        body = [f"<!doctype html><meta charset=utf-8><title>{html.escape(r['file'])}</title><style>{css}</style>",
                f"<p><a href='index.html'>&larr; index</a></p><h2>{html.escape(r['label'])}</h2><div class=src>"]
        for i, text in enumerate(src, 1):
            cls, title, vc = "", "", ""
            if i in L:
                vc = str(L[i])
                if i in X:
                    cls, title = "excl", X[i]
                elif L[i] == 0:
                    cls = "miss"
                elif i in B and any(x == 0 for x in B[i]):
                    cls = "part"
                    title = f"branches {sum(1 for x in B[i] if x > 0)}/{len(B[i])}"
                else:
                    cls = "hit"
                if i in B and not title:
                    title = f"branches {sum(1 for x in B[i] if x > 0)}/{len(B[i])}"
            elif i in X and in_ranges(i, r["ranges"]):
                cls, title = "excl", X[i]
            body.append(f"<div class='{cls}' title='{html.escape(title)}'><span class=ln>{i}</span>"
                        f"<span class=vc>{vc}</span>{html.escape(text)}</div>")
        body.append("</div>")
        (out / page).write_text("\n".join(body), encoding="utf-8")
    idx.append("</table>")
    (out / "index.html").write_text("\n".join(idx), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("xml")
    ap.add_argument("out")
    ap.add_argument("--repo", default=str(ROOT.parent.parent))
    ap.add_argument("--fail-under", type=float, default=None, help="net core line coverage threshold")
    ap.add_argument("--uncovered", action="store_true", help="list uncovered/partial lines per file")
    a = ap.parse_args()
    scope, excl = load_scope()
    lines, branches, excluded = collect(Path(a.xml), scope, excl)
    rows = summarize(scope, lines, branches, excluded)
    tot = print_table(rows)
    if a.uncovered:
        for r in rows:
            if r["uncovered_lines"] or r["partial_branch_lines"]:
                print(f"\n{r['label']}\n  uncovered: {ranges_str(r['uncovered_lines'])}\n  partial branches: {ranges_str(r['partial_branch_lines'])}")
    out = Path(a.out)
    write_html(out, rows, lines, branches, excluded, Path(a.repo))
    (out / "summary.json").write_text(json.dumps(rows, indent=1))
    print(f"\nHTML report: {out / 'index.html'}")
    if a.fail_under is not None:
        c = tot["core"]
        if pct(c[4], c[5]) < a.fail_under:
            print(f"net core line coverage {pct(c[4], c[5]):.1f}% < {a.fail_under}%", file=sys.stderr)
            sys.exit(2)


if __name__ == "__main__":
    main()
