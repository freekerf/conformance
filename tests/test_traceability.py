"""doc/traceability.md stays true: every white-box test has exactly one row, every
portable reference exists, and the summary counts match the rows. Host-independent."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "doc" / "traceability.md"
ROW = re.compile(r"^\| `(test_\w+\.py)::(test_\w+)` \| (.*?) \| (yes|no[^|]*) \| (.*?) \| (.*?) \| (.*?) \|$")


def rows():
    return [m.groups() for m in map(ROW.match, DOC.read_text().splitlines()) if m]


def defined_tests(folder):
    out = {}
    for f in sorted((ROOT / "tests" / folder).glob("test_*.py")):
        for name in re.findall(r"^def (test_\w+)", f.read_text(), re.M):
            out[f"{f.name}::{name}"] = f
    return out


def test_every_whitebox_test_has_exactly_one_row():
    listed = [f"{r[0]}::{r[1]}" for r in rows()]
    assert len(listed) == len(set(listed)), "a test is listed twice"
    whitebox = set(defined_tests("whitebox"))
    assert set(listed) == whitebox, {"missing": sorted(whitebox - set(listed)), "unknown": sorted(set(listed) - whitebox)}


def test_portable_references_exist():
    protocol = set(defined_tests("protocol"))
    goldens = {p.stem for p in (ROOT / "fixtures" / "gcode").glob("*.nc")}
    for r in rows():
        for ref in re.findall(r"`([^`]+)`", r[4]):
            if ref.startswith("golden:"):
                assert ref[7:] in goldens, ref
            elif ref.startswith("diff:"):
                assert ref[5:] in ("gcode", "protocol"), ref
            else:
                assert ref in protocol, ref


def test_summary_counts_match_the_rows():
    rs = rows()
    observable = [r for r in rs if r[3] == "yes"]
    compared = [r for r in observable if r[4] != "—"]
    text = DOC.read_text()
    assert f"White-box tests (rows): **{len(rs)}**" in text
    assert f"through the HostAdapter or `analyze`: **{len(observable)}**" in text
    assert f"-> **{len(compared)} now**" in text
    assert f"not compared yet: **{len(observable) - len(compared)}**" in text
