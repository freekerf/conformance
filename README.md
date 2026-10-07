# FreeKerf conformance suite

Part of [FreeKerf](https://github.com/freekerf), the GPL-3.0-or-later successor of
LaserGRBL written in Rust. This repository is the executable specification of the
current LaserGRBL core: the Rust core in [`freekerf/freekerf`](https://github.com/freekerf/freekerf)
runs the portable layers (protocol and golden) against its own build. The Rust core
does **not** have to reproduce the quirks in [FINDINGS.md](FINDINGS.md); every
intentional difference is recorded in `DIVERGENCES.md` of the Rust repository.

The LaserGRBL sources under test are **not** vendored: point `LASERGRBL_REPO` to a
LaserGRBL checkout. The suite (line ranges in `scope.toml`/`exclusions.toml`,
goldens) was validated against commit `bf15096` of the fork used during
development (upstream [arkypita/LaserGRBL](https://github.com/arkypita/LaserGRBL)
plus SVG colour layers, DXF import and a new button); other commits may need the
goldens and line ranges regenerated.

Python tests that pin the behaviour of LaserGRBL's C# core and of its importers
(see [SCOPE.md](SCOPE.md)) so a future Rust rewrite can be checked against it. Layers:

| layer | directory | talks to | portable to Rust? |
|-------|-----------|----------|-------------------|
| white-box | `tests/whitebox/` | the C# core classes in-process (pythonnet on Mono) | no: this is what drives C# coverage |
| importers white-box | `tests/importers/` | the C# importer classes in-process | no: errors, truth tables, helpers the goldens do not reach |
| protocol (black-box) | `tests/protocol/` | a host through `HostAdapter`, a fake Grbl 1.1 device on a PTY | yes: write a Rust `HostAdapter` |
| golden (G-code) | `tests/golden/test_golden.py` | `fixtures/gcode/*.nc` -> `fixtures/golden/*.json` | yes: write a Rust analyzer returning the same JSON |
| golden (importers) | `tests/golden/test_importers.py` | `fixtures/importers/cases/*.json` (+ `inputs/`) -> `fixtures/golden/importers/*.json` | yes: write a Rust `run_case` returning the same JSON (cases marked `platform_dependent` depend on GDI+) |

Results of the last run: [COVERAGE.md](COVERAGE.md). Suspicious behaviour found
along the way: [FINDINGS.md](FINDINGS.md).

## Setup (once)

Requirements (Linux): Mono 6.8 (`mono`, `xbuild`, `mcs`), `gcc`, `rsync`, `curl`,
`unzip`, and [uv](https://docs.astral.sh/uv/). No .NET SDK, no Wine, no display.

```bash
export LASERGRBL_REPO=/path/to/LaserGRBL
make setup        # uv sync: Python 3.12 venv with pytest, pythonnet, pyserial
```

## Running against FreeKerf (Rust)

The *protocol* and *golden (G-code)* layers also run against FreeKerf, through
`freekerf host --stdio` (`RustHost`) and `freekerf analyze --json`:

```bash
cargo build -p freekerf-cli                          # in the freekerf repository
FREEKERF_BIN=/path/to/freekerf/target/debug/freekerf make test-rust
```

`make test-rust` needs neither Mono nor `LASERGRBL_REPO`. A test where FreeKerf
intentionally differs from LaserGRBL is marked `@pytest.mark.rust_divergence("DIV-NNN")`
(the id of the entry in FreeKerf's `doc/divergences.md`): for the Rust host it is
expected to fail (strict xfail), the C# host runs it unchanged. A golden case gets the
same mark from a first line `; rust_divergence: DIV-NNN` in its `.nc` file. Never delete
such a test or loosen its assertion. The importer goldens are skipped for the Rust host until
FreeKerf's importers exist (its milestone M2).

## Commands

```bash
make test         # build (Mono, in ~/.cache) + run the whole suite
make coverage     # build + instrument with AltCover + run + report (terminal + HTML)
make golden       # rewrite fixtures/golden/*.json from current behaviour (review the diff!)
make test-rust    # protocol + golden (G-code) layers against FreeKerf (see above)
make clean        # remove ~/.cache/freekerf-conformance/{build,coverage}
```

`PYTEST_ARGS` is passed through, e.g. `make test PYTEST_ARGS="-k protocol -x"`.
Build and instrumentation outputs live in `~/.cache/freekerf-conformance/` (override with
`LASERGRBL_BUILD_DIR`, `LASERGRBL_COV_DIR`); the LaserGRBL repo itself is never written to.

The coverage report (HTML + `summary.json`) is written to `core-tests/coverage-report/`
(git-ignored; override with `REPORT_DIR`). Build outputs and the instrumented
binaries stay in `~/.cache/freekerf-conformance/` because they are large and disposable.

## How it works

### Build (`scripts/build_lasergrbl.sh`)

1. `rsync` of the repo (without `.git`, `bin`, `obj`, `LaserGRBL.Tests`)
   to `~/.cache/freekerf-conformance/build/src`.
2. The three Mono build workarounds from the reference script (only in the copy):
   `MyPictureBox.designer.cs` case, `System.Diagnostics.Eventing` using, and the
   `PbBuffer.ProgressBar.SetState` call.
3. `xbuild` in **Debug** (symbols `.mdb`, no optimizations).
4. `native/lgshim.c` -> `liblgshim.so`, and a generated Mono global config
   (`mono-config`, from `/etc/mono/config`) that routes:
   * `kernel32!QueryPerformanceCounter/Frequency/GetTickCount` (used by
     `Tools.HiResTimer`) to the shim: without it every timer in the core throws
     `EntryPointNotFoundException` on Linux;
   * `MonoPosixHelper!set_signal` to the shim: Mono's `SerialPort` always sets
     DTR/RTS when opening, which fails with `ENOTTY` on a pseudo terminal; the
     shim ignores that error, so the core's own `UsbSerial` can open a PTY;
   * `gdiplus!GdipCreateBitmapFromScan0` to the shim, which creates the bitmap with
     the real libgdiplus and gives it 96 dpi (libgdiplus: 0 dpi, Windows: 96);
   * `gdiplus!GdipImageRotateFlip` to the shim: libgdiplus ignores pure flips on a
     bitmap that was drawn with a Graphics, the shim does them as two rotations.
5. `tools/TestSupport.cs` -> `TestSupport.dll` next to the exe (in-memory
   `IComWrapper`, event recorder, emulator and image processor probes; see "Threading rule").

### White-box path (pythonnet)

`lasergrbl_harness/runtime.py` sets an isolated `HOME`/`XDG_CONFIG_HOME` (so
`LaserGRBL.Settings.bin` and the other data files go to a temp dir), unsets
`DISPLAY`, forces the `C` locale, enables Mono explicit null checks, points
`MONO_CONFIG` to the generated config and loads `LaserGRBL.exe` with
`pythonnet.load("mono")`.

`GrblCore` is built without the WinForms app (`core_rig.py`):

* the `syncro` Control is an *uninitialized* `Control` (a real one needs an X
  display); its `InvokeRequired` is false, so events fire synchronously;
* `PreviewForm`/`JogForm` are `null` (only stored by `HotKeysManager`);
* the protected `com` field is replaced by `LoopbackCom` (in-memory) or the core is
  configured with `UsbSerial` on a PTY;
* the static `Settings` dictionary is cleared before every test; the first load
  uses a pre-seeded settings file from "4.4.0" to exercise the load/migration paths;
* `SafetyCountdown` is disabled via its setting (it would open a dialog).

Two driving styles: **stepped** (no threads: call `ThreadTX`/`SendLine`/
`ManageReceivedLine` directly, fully deterministic) and **live** (the real TX/RX
threads, with bounded waits on conditions).

### Protocol path

`FakeGrbl` (`fake_grbl.py`) is a transport-independent Grbl 1.1 model: real-time
commands, RX buffer accounting (`rx_used`, `max_rx_used`, `overflows`), manual or
automatic `ok`, error rules, alarms, `$$`/`$I`/`$X`/`$H`/`$C`/`$J=`/`$N=V`,
overrides, feed hold, door, soft reset; for harder cases a silent status (`mute_status`),
lost or garbled `ok`s, `WPos` and Grbl 0.9 reports, extra report fields, and `M114` for
Marlin hosts. `PtyLink` puts it behind `/dev/pts/N`; the host
(`CSharpHost` today) opens that path like a real serial port.

To run the protocol layer against another host, implement the `HostAdapter`
protocol in `lasergrbl_harness/host.py` (`RustHost` is the FreeKerf one) and select
it with `LASERGRBL_HOST`; the
golden layer needs an analyzer in `lasergrbl_harness/golden.py` and an importer
runner in `lasergrbl_harness/importers.py` (`run_case`, case format in its
docstring). Neither layer loads the CLR unless `LASERGRBL_HOST=csharp` (the default).

### Importer golden cases

A case is a small JSON file: kind (`generator`, `hershey`, `svg`, `dxf`, `svg_text`,
`raster`, `potrace`, `centerline`, `image_processor`, `image_op`), its input (an svg/dxf under `fixtures/importers/inputs/`,
pixel rows or ASCII art, or parameters), the options (layers, `L2LConf` fields,
vectorize options) and optional
LaserGRBL settings. The result is the G-code of the resulting `GrblFile` (or the
pixels of an image operation) plus a summary (count, estimated time, ranges); a
conversion that throws records `error` (the C# `GrblFile` swallows it). To add a
case, write the JSON, run `make golden` and review the new file.

### Coverage (`scripts/instrument.sh`, `scripts/coverage_report.py`)

AltCover 9 (NuGet, the .NET Framework build runs on Mono and reads `.mdb`
symbols) instruments only the files listed in `scope.toml`. Before that,
`tools/FixSymbols.cs` (Mono.Cecil) drops the sequence points that mcs puts right
after IL prefixes (`constrained.` etc.): AltCover would insert its probe between
the prefix and the call and produce invalid IL. The recorder is flushed at the end
of the pytest session (and by subprocess-based tests), and visit counts accumulate
across processes. The report filters by file and line range, applies
`exclusions.toml` and prints raw and net numbers.

## Known issues / rules for writing tests

* **Threading rule (pythonnet + Mono 6.8):** only the main Python thread may call
  into the CLR, and CLR threads must never run Python code. Breaking it deadlocks
  the process. That is why the in-memory transport, the event recorder and the
  emulator probes are C# (`tools/TestSupport.cs`), why the loopback device is
  pumped by the main thread inside `rig.wait()`, and why core APIs that block the
  caller (`WriteConfig`, `RefreshConfig`) are tested over the PTY link.
* Python `int` passed where the CLR expects `object` becomes a non-serializable
  `PyInt`: use `System.Int32(...)` for values stored in `Settings`.
* Tearing down the embedded Mono deadlocks in `mono_jit_cleanup`; the session ends
  with `os._exit` after flushing coverage (`tests/conftest.py`).
* Mono's `SerialPort.ReadLine` blocks in `poll()`; close the PTY (hang up) before
  closing a host, otherwise `CloseCom` waits 5 s for the reader thread. The only
  test that intentionally closes from the host side (`test_disconnect_closes_the_line`)
  takes those 5 s.
* clr_loader warns that Mono < 6.12 is "problematic": with the rules above it has
  been stable (the suite was run 3 times in a row without failures).
* `SvgConverter.gcode` (the SVG/DXF G-code writer) is a static class that keeps
  state between imports and reads the firmware type once: every importer case
  restores a snapshot of its fields taken at the first use (`reset_gcode_statics`).
* A new in-memory `Bitmap` has 0 dpi on libgdiplus (96 on Windows) and
  `ImageTransform.ResizeImage` throws on it: `importers.make_bitmap` sets 96 dpi.
* Centerline calls `autotrace.exe` (Windows). `importers.fake_autotrace` replaces it
  with a shell double: it sets the runtime's argv[0] (`mono_runtime_set_main_args`;
  `Application.ExecutablePath` throws without one) to a temp folder holding
  `Autotrace/autotrace.exe` and resets it afterwards.
* `Settings.GetObject<T>` returns a stored value only if its type is exactly `T`
  (otherwise the default, silently): case settings are converted by
  `importers.apply_settings` (ints to Int32, floats to Double, the few float
  settings to Single).
* Image operations drawn through GDI+ (grayscale, threshold, invert, resize) are
  libgdiplus results (`platform_dependent` in their case files); the libgdiplus
  "nearest neighbor" resize blends pixels.

## Layout

```
pyproject.toml  uv.lock  Makefile
scope.toml  exclusions.toml          coverage scope and justified exclusions
scripts/   build_lasergrbl.sh  make_mono_config.py  instrument.sh  get_altcover.sh  coverage_report.py
native/    lgshim.c                  kernel32 timer, set_signal, Bitmap dpi and flip shims
tools/     TestSupport.cs  FixSymbols.cs
src/lasergrbl_harness/
           runtime.py bootstrap.py clr_util.py core_rig.py fake_grbl.py links.py host.py golden.py importers.py waiting.py
tests/     conftest.py
           whitebox/  (+ subproc/ scripts run in fresh processes)
           importers/
           protocol/
           golden/
fixtures/  gcode/*.nc  golden/*.json
           importers/cases/*.json  importers/inputs/{svg,dxf}/  golden/importers/*.json
SCOPE.md  COVERAGE.md  FINDINGS.md
```

## License

GPL-3.0-or-later (see [LICENSE](LICENSE) and [NOTICE](NOTICE)).
