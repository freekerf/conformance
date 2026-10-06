#!/usr/bin/env bash
# Builds LaserGRBL.exe with Mono xbuild in a throwaway copy of the repo.
# Nothing inside the repo is written: the copy lives in $LASERGRBL_BUILD_DIR
# (default ~/.cache/freekerf-conformance/build). Prints the path of the exe on success.
#
# The three source tweaks are Linux/Mono build workarounds only (same as the
# reference ~/.cache/lasergrbl-tests/run-tests.sh); none touches core code.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${LASERGRBL_REPO:?set LASERGRBL_REPO to a LaserGRBL checkout (validated at commit bf15096, see README)}"
REPO="$(cd "$LASERGRBL_REPO" && pwd)"
WORK="${LASERGRBL_BUILD_DIR:-$HOME/.cache/freekerf-conformance/build}"

mkdir -p "$WORK"
# --delete keeps the copy in sync; bin/obj of the copy are kept for incremental builds
rsync -a --delete --exclude .git --exclude bin --exclude obj --exclude laser-novo \
	--exclude LaserGRBL.Tests "$REPO/" "$WORK/src/"
S="$WORK/src/LaserGRBL"

cp "$S/UserControls/MyPictureBox.Designer.cs" "$S/UserControls/MyPictureBox.designer.cs"  # case-sensitive filesystem
sed -i '/System.Diagnostics.Eventing/d' "$S/PreviewForm.cs"                                # namespace missing in Mono
sed -i 's#^\(\s*PbBuffer.ProgressBar.SetState\)#//\1#' "$S/MainForm.cs"                    # mcs ambiguity (progress bar color only)

# Debug configuration: full pdb/mdb symbols are needed by the coverage tool,
# and no optimizations keeps sequence points 1:1 with source lines.
CONF="${LASERGRBL_CONFIGURATION:-Debug}"
LOG="$WORK/xbuild.log"
if ! xbuild "$S/LaserGRBL.csproj" /p:Configuration="$CONF" /p:LangVersion=experimental \
	/p:DebugType=portable /p:DebugSymbols=true /v:minimal >"$LOG" 2>&1; then
	grep -E "error" "$LOG" | head -40 >&2
	echo "LaserGRBL build failed (see $LOG)" >&2
	exit 1
fi
EXE="$S/bin/$CONF/LaserGRBL.exe"
test -f "$EXE" || { echo "exe not found: $EXE" >&2; exit 1; }

# native shims (kernel32 timers for Tools.HiResTimer; DTR/RTS on a PTY for Mono's
# SerialPort), routed through a generated Mono global config ($WORK/mono-config)
SHIM="$WORK/liblgshim.so"
gcc -shared -fPIC -O2 -o "$SHIM" "$HERE/../native/lgshim.c"
"$HERE/make_mono_config.py" "$WORK/mono-config" "$SHIM"

# test-side C# helpers (in-memory transport, event recorder), next to the exe
mcs -nologo -target:library -out:"$(dirname "$EXE")/TestSupport.dll" -r:"$EXE" -r:System.Windows.Forms.dll \
	"$HERE/../tools/TestSupport.cs"

echo "$EXE"
