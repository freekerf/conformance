#!/usr/bin/env bash
# Downloads (once) the AltCover NuGet package into ~/.cache and prints the path of
# the .NET Framework build of AltCover.exe, which runs on Mono.
set -euo pipefail
VER="${ALTCOVER_VERSION:-9.0.145}"
DIR="$HOME/.cache/freekerf-conformance/tools/altcover-$VER"
EXE="$DIR/tools/net472/AltCover.exe"
if [ ! -f "$EXE" ]; then
	mkdir -p "$DIR"
	curl -sSfL -o "$DIR.nupkg" "https://api.nuget.org/v3-flatcontainer/altcover/$VER/altcover.$VER.nupkg"
	(cd "$DIR" && unzip -q "$DIR.nupkg")
fi
echo "$EXE"
