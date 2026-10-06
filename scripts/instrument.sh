#!/usr/bin/env bash
# Instruments the Debug LaserGRBL.exe with AltCover (OpenCover format), restricted to
# the source files listed in scope.toml. Output: $LASERGRBL_COV_DIR (default
# ~/.cache/freekerf-conformance/coverage) with instr/ (instrumented binaries) and
# coverage.pristine.xml (the empty report; the recorder writes visits into coverage.xml).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
WORK="${LASERGRBL_BUILD_DIR:-$HOME/.cache/freekerf-conformance/build}"
COV="${LASERGRBL_COV_DIR:-$HOME/.cache/freekerf-conformance/coverage}"
ALTCOVER="${ALTCOVER_EXE:-$("$HERE/get_altcover.sh")}"
BIN="$WORK/src/LaserGRBL/bin/${LASERGRBL_CONFIGURATION:-Debug}"

# inclusion filter on source file *names* (AltCover: a leading ? makes it an inclusion filter)
FILTER="?$(python3 - "$ROOT/scope.toml" <<'PY'
import re, sys, tomllib
files = tomllib.load(open(sys.argv[1], "rb"))["file"]
print("|".join("^" + re.escape(f["path"].split("/")[-1]) + "$" for f in files))
PY
)"

# mcs puts some sequence points right after IL prefixes (constrained. etc.); AltCover
# would insert its probe there and break the IL. Strip those points from a copy first.
AC_DIR="$(dirname "$ALTCOVER")"
FIX="$COV/tools/FixSymbols.exe"
mkdir -p "$COV/tools"
cp "$AC_DIR/Mono.Cecil.dll" "$AC_DIR/Mono.Cecil.Mdb.dll" "$COV/tools/"
mcs -nologo -out:"$FIX" -r:"$COV/tools/Mono.Cecil.dll" -r:"$COV/tools/Mono.Cecil.Mdb.dll" "$ROOT/tools/FixSymbols.cs"
rm -rf "$COV/prep" "$COV/instr" && mkdir -p "$COV/prep"
rsync -a "$BIN/" "$COV/prep/"
mono "$FIX" "$BIN/LaserGRBL.exe" "$COV/prep/LaserGRBL.exe" >"$COV/fixsymbols.log"

mono "$ALTCOVER" --inputDirectory="$COV/prep" --outputDirectory="$COV/instr" \
	--report="$COV/coverage.xml" --reportFormat=OpenCover --fileFilter="$FILTER" >"$COV/altcover.log" 2>&1 \
	|| { cat "$COV/altcover.log" >&2; exit 1; }
cp "$COV/coverage.xml" "$COV/coverage.pristine.xml"
echo "$COV/instr"
