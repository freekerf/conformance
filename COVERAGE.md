# C# coverage of the core and the importers

Command: `make coverage` (build → AltCover instrumentation → pytest on the
instrumented exe → report filtered to [`scope.toml`](scope.toml)). HTML:
`core-tests/coverage-report/index.html`.

Last run: **844 tests passed** (564 core + 280 importers), 112 s of tests
(118 s wall including build and instrumentation). Without coverage the suite takes
about 90 s; it was run 3 times in a row with no failures.

## Tool choice (spike)

| option | result |
|--------|--------|
| Mono log profiler (`--profile=log:coverage` + `mprof-report`) | not usable: the Debian/Ubuntu Mono 6.8 install has `mprof-report` but no `libmono-profiler-*` modules, and the coverage mode was dropped from the log profiler in Mono 5.x anyway; installing other system packages was out of scope |
| **AltCover 9.0.145** (NuGet, .NET Framework build on Mono) | **chosen**. Reads mcs `.mdb` symbols, OpenCover XML with line and branch points, works with the exe loaded by pythonnet. Two fixes were needed: `tools/FixSymbols.cs` drops 346 sequence points that mcs places right after IL prefixes (otherwise AltCover emits invalid IL: "constrained call ... is not assignable"), and the recorder is flushed explicitly (`Instance.FlushFinish()`) because the embedded Mono is never shut down. Visit counts accumulate across processes, so subprocess tests (static constructors) count too. |

## Numbers per file

"net" = after the justified exclusions in [`exclusions.toml`](exclusions.toml).

| file | lines | branches | net lines | net branches |
|------|-------|----------|-----------|--------------|
| Core/GrblCore.cs | 2698/2939 (91.8 %) | 1182/1382 (85.5 %) | 100 % | 91.1 % |
| Core/MarlinCore.cs | 60/62 | 20/32 | 100 % | 67.9 % |
| Core/SmoothieCore.cs | 15/15 | – | 100 % | 100 % |
| Core/VigoCore.cs | 83/83 | 21/22 | 100 % | 95.5 % |
| GrblCommand.cs | 308/308 | 203/206 | 100 % | 99.5 % |
| StateBuilder.cs | 295/296 | 158/162 | 100 % | 97.5 % |
| Settings.cs | 128/128 | 46/48 | 100 % | 95.8 % |
| GrblFile.cs (G-code ranges) | 237/237 | 85/92 | 100 % | 92.4 % |
| GrblEmulator/Grblv11Emulator.cs | 224/224 | 67/68 | 100 % | 98.5 % |
| ComWrapper/Emulator.cs | 60/60 | 20/20 | 100 % | 100 % |
| ComWrapper/UsbSerial.cs | 119/125 | 32/36 | 100 % | 94.1 % |
| Tools/RetainedSetting.cs | 12/12 | 3/4 | 100 % | 75 % |
| Tools/MathHelper.cs (LinearDistance) | 5/5 | – | 100 % | 100 % |
| **total core** | **4244/4494 (94.4 %)** | **1837/2072 (88.7 %)** | **100 %** | **92.8 %** |

Helper tier (informative, no target): ExpressionEvaluator 34 % (third-party; only
the expression features used by custom code are exercised), Cronometro 54 %,
ThreadClass 88 %, CsvDictionary 100 % lines.

**Line target: reached** (every in-scope line is executed or excluded with a
reason). **Branch target: not reached** (92.8 % net); the rest is listed below.

## Excluded lines (covers all 251 unexecuted lines; details in `exclusions.toml`)

| category | where | why it is not tested |
|----------|-------|----------------------|
| ui | GrblCore 648-657, 676-703, 711-792, 798-806, 838, 862-895, 901-934, 1336, 1369-1390, 1396, 1447, 1553, 4575-4576 | file/save dialogs, MessageBox, Cursor, resume/position/laser-selector dialogs, SafetyCountdown cancel. They need WinForms with a display; the harness is headless on purpose. Their non-UI halves (GrblFile load/save, ContinueProgramFromKnown, RunProgramFromStart) are tested directly |
| marshal | GrblCore 597, 608, 619 | `Control.BeginInvoke` when `InvokeRequired`; needs a real Control with a message loop |
| windows | GrblCore 405-428 | WMI enumeration of CH340 drivers; System.Management throws on Mono before the loop |
| platform | UsbSerial 187-192 | reads .NET Framework's private `internalSerialStream`; Mono's SerialPort has no such field |
| dead | GrblCore 240, 463, 582-590, 847-857, 1046-1049, 1144-1146, 1219-1222, 1264-1267, 2137-2140, 2388-2390, 3416-3426, 3952-3956, 4730; MarlinCore 59-61; StateBuilder 199 | no caller (`RiseJogStateChange`, `GetEncoder`, `BufferIsFull`, `ManageOrturBlockingAlarm`, `StringToGCode`, `CompareValues`, `ReadConfigCountException`) or unreachable by construction (impossible conditions, catch blocks around code that cannot throw). (`GrblFile.IsEven`, excluded before, is now reached through the Line2Line raster.) |
| external | GrblCore 3252 | `HelpOnLine` opens the browser |
| race | GrblCore 4765 | only reached when renaming the counter file to `.old` failed |
| 3d | GrblCommand 167, 331 | non-null branch of `LinkedDisplayList?.Invalidate()` (SharpGL preview) |

## Remaining partial branches (net), by reason

Branch points are IL-level: one `a && b && c` produces one point per operand
outcome, and the compiler adds points for `foreach`, `using` and `?.`. The lines
below have at least one outcome never taken.

| reason | lines |
|--------|-------|
| operand that cannot take the other value at run time (field never null, `Split` always ≥ 1 element, static ctor runs once, value checked earlier) | GrblCore 462, 516, 1023, 1501, 1511-1521 (`com == null` never), 2170, 2190, 2660, 2708, 3358-3361, 3389, 4488, 4729; MarlinCore 58, 118; StateBuilder 196, 206; GrblFile 97, 145; UsbSerial 104 |
| compiler-generated (`foreach` enumerator disposal, `using` null checks, `?.` with/without subscriber) | GrblCore 630, 638, 820, 3391, 3846, 4664, 4692-4693; Settings 68, 180; GrblFile 84, 148; GrblCommand 174; Grblv11Emulator 159; RetainedSetting 29; GrblCore 174 (`as` cast in Equals) |
| behind UI (the UI half is excluded, the condition line is not) | GrblCore 594-618 (`InvokeRequired` true), 646, 675, 705, 861, 900, 1333 (partially executed job → ResumeJobForm), 1395, 1446, 3246 (disconnect during a job asks with a MessageBox); GrblFile 105, 368 (`CheckInUse` → MessageBox) |
| timing or thread interleaving that cannot be forced deterministically | GrblCore 987 (5 s global cap of the `$I` reader), 1156, 1211, 1256, 1300 (contents of the shared log while a write is in flight), 1249, 1294 (port closed during the busy-wait), 2245, 2257 (buffer-stuck operand combinations), 2841 (CH340 mode with the port closed), 3123, 3134 (cooling state combinations during hold), 4541, 4545 (negative / > 600 s timer deltas) |
| remaining operand combinations of guards and permissions, low value individually (e.g. issue already recorded, program running and version unknown, every jog direction on Grbl 0.9) | GrblCore 511, 1464, 1485, 1632, 1726, 1735, 1738, 1749, 1796, 1859-1865, 2381, 2602, 2616, 2652, 2820, 2925, 3005, 3054, 3061, 3079, 3085, 3097, 3148, 3160, 3209, 3258, 3610, 3629-3671 (TimeProjection guards), 4265, 4286, 4764, 4778, 4807; MarlinCore 55, 77, 86; VigoCore 75; StateBuilder 464, 466; GrblFile 1801; UsbSerial 58 |

The last group is reachable; it was left as the stopping point (diminishing
returns). Each is a single extra `assert` on an existing fixture if the Rust port
needs the exact truth table.

## How the hard parts were reached

* Static constructors (`Settings`, `LaserLifeHandler`) with different files on disk:
  fresh subprocesses (`tests/whitebox/subproc/`), coverage accumulates.
* Timers (10 s connect timeout, 5 s hang detection, 10 s buffer-stuck): the
  `ElapsedFromEvent` start time is moved into the past via reflection instead of
  waiting. The two 10 s `$$`/`$I` reply timeouts are real waits (local variables).
* Statistics upload: a local HTTP endpoint in a subprocess.
* WinForms paths that only *start* UI: executed headless; the UI call throws and
  the core's own catch is covered.

## Importers (tier "importers", phase 2)

Same command and target (100 % lines, branches as close as reasonable), reported
separately. Scope: [SCOPE.md](SCOPE.md), "Tier importers". Tests: 126 golden cases
(`tests/golden/test_importers.py`, plus a check for orphan goldens) + 153 white-box
tests (`tests/importers/`).

| file | lines | branches | net lines | net branches |
|------|-------|----------|-----------|--------------|
| GrblFile.cs (importer ranges, incl. Potrace 379-506 and Centerline 1421-1468) | 648/660 | 279/296 | 100 % | 94.3 % |
| RasterConverter/ImageProcessor.cs (without the preview drawing) | 646/653 | 217/236 | 100 % | 91.9 % |
| Autotrace/Autotrace.cs | 46/49 | 11/14 | 100 % | 78.6 % |
| Hershey/Hershey.cs | 99/99 | 31/32 | 100 % | 96.9 % |
| SvgConverter/GCodeFromSVG.cs | 985/1095 | 399/543 | 100 % | 82.8 % |
| SvgConverter/gcodeRelated.cs | 183/381 | 70/162 | 100 % | 89.7 % |
| SvgConverter/SvgColorLayer.cs | 122/122 | 62/63 | 100 % | 98.4 % |
| SvgConverter/SvgFilling.cs | 104/105 | 50/52 | 100 % | 96.2 % |
| SvgConverter/VectorImportSource.cs | 30/30 | 4/4 | 100 % | 100 % |
| SvgConverter/VectorDrawing.cs | 100/100 | 32/32 | 100 % | 100 % |
| SvgConverter/VectorGCode.cs | 68/68 | 33/34 | 100 % | 97.1 % |
| SvgConverter/DxfReader.cs | 512/512 | 258/264 | 100 % | 97.7 % |
| SvgConverter/ArcFitter.cs | 82/82 | 42/44 | 100 % | 95.5 % |
| SvgConverter/BezierTools.cs | 39/39 | 16/16 | 100 % | 100 % |
| RasterConverter/ImageTransform.cs | 314/335 | 105/124 | 100 % | 87.5 % |
| **total importers** | **3978/4330 (91.9 %)** | **1609/1916 (84.0 %)** | **100 %** | **91.1 %** |

Helper tier additions (no target): PotraceClipper 97 %, Cyotek ErrorDiffusionDithering
94 %, RandomDithering 92 %, ImageUtilities 80 % lines; CsPotrace 77 %, CsPotraceExport
84 %, CsPotraceExportGCODE 68 %, BezierToBiarc 58-100 % lines. CsPotrace is measured
only: the `potrace_*` golden cases (12) pin what it produces through
`LoadImagePotrace`; the unexecuted parts are mostly the SVG export (`getSVG`, unused
by LaserGRBL), turn policies other than the default and the fallbacks of the biarc
approximation.

**Line target: reached. Branch target: not reached (91.1 % net).** Most of the gap
is code behind hard-coded options (below).

### Excluded lines (all 352 unexecuted importer lines; details in `exclusions.toml`)

| category | where | why it is not tested |
|----------|-------|----------------------|
| fixed-option | GCodeFromSVG 316, 367, 409-410, 600-604, 763-769, 917-1195 (`svgNodesOnly` branches), 1377-1381, 1409-1412, 1450-1460, 1484-1487; gcodeRelated 122, 328-331, 422-466, 556-563, 613-615, 626-728 | private options that are hard-coded and never changed (`svgComments`, `svgNodesOnly`, `gcodeReduce`, `svgConvertToMM = true`, `gcodeCompress = true`, `gcodeNoArcs = false`, drag compensation off; every caller passes `avoidG23 = false`): the code cannot run in LaserGRBL. It could be reached by flipping the fields through reflection, but that would characterize behaviour no user can get |
| dead | GrblFile 311, 328, 836-838, 1297-1305; GCodeFromSVG 119-122, 451-453, 728, 807-832, 835-867, 1253-1255, 1303-1305, 1505; gcodeRelated 103-111, 126-161, 167-168, 303-306, 311-314, 509-512, 533-535, 569-587, 592-593; ImageTransform 359, 366, 373, 390-404, 443-448 | no caller (`map`, `DirectionChange`, `convertFromFile`, the color filter of `convertFromText`, `getIntGCode` & co., `splitLine`, overloads with Z or floats, `Format32bppArgbCopy`, `DirectBitmap.Dispose`) or impossible by construction (negative separator length, unknown basic shape, negative `CalculateVectorAngle`, result below 0 in `ColorSubstitution`) |
| defensive | SvgFilling 62 | Clipper `Execute` failure, not produced by valid input |
| dead (threads, wrapper) | ImageProcessor 871-873; Autotrace 65-67 | `AbortThread` called from the processing thread itself (only the UI thread calls it); `ToHexString` has no caller |
| race | ImageProcessor 865-868 | `AbortThread` forcing `Thread.Abort` when the preview thread is still running 100 ms after the exit request |

### Remaining partial branches (net), by reason

| reason | lines |
|--------|-------|
| hard-coded option (the condition line runs, its other outcome cannot) | GCodeFromSVG 270, 313, 364, 408, 412, 599, 632, 638, 657, 665, 676, 686, 762, 780, 912, 916, 927, 942, 951, 964, 982, 1000, 1011, 1015, 1029, 1039, 1043, 1065, 1084, 1088, 1106, 1122, 1126, 1151, 1165, 1169, 1192, 1206, 1399, 1408, 1449, 1461, 1483; gcodeRelated 119, 327, 522, 612 |
| compiler-generated (`foreach` disposal, `using`, `switch` on strings) | GrblFile 438-440 (`using` in the Potrace raster filling); ImageProcessor 129-130, 894, 916, 1077, 1121, 1147, 1149, 1159; Autotrace 85; GCodeFromSVG 139, 172, 406, 593, 743, 784; SvgColorLayer 135; VectorGCode 41; DxfReader 471-472; ImageTransform 55-56, 76, 100 |
| race (thread state) | ImageProcessor 861, 864 (preview thread already stopped / abort from itself), 882 (`MustExit` null), 892 (exit requested during a demo preview) |
| operand that cannot take the other value | GrblFile 205 (a trimmed non-empty line is never an empty command), 310, 327, 467 (`plist != null`, always true), 1140, 1455, 1458 (the SVG writer emits no blank or comment-only lines here); ImageProcessor 910 (no tool after NoProcessing), 1074; Autotrace 30 (`ReadToEnd` never returns null), 57 (the png is always written) (ExtractSegment only sees H/V/D); Hershey 322 (the regex only matches X/Y); GCodeFromSVG 445, 466, 477, 492, 504 (`transform != null`), 528, 717, 805, 934-935 (firstX is never null while a subpath is open), 1252, 1477, 1504; gcodeRelated 508, 514, 532 (no caller passes Z or a rapid with feed); SvgFilling 61; ArcFitter 85, 106; ImageTransform 221 (never a null dithering), 345-351 (`< 255 + threshold` always true), 358, 365, 372, 489 |
| platform | GrblFile 202: the G-code text is split on `Environment.NewLine` characters; with CRLF text on Linux (`\n` only) a blank line leaves a lone `\r`, on Windows the split removes it. Not produced by the current writers |
| behind UI | GrblFile 381, 540, 586, 667, 789, 1423: `CheckInUse()` true shows a MessageBox |
| reachable, low value | ImageProcessor 327, 329 (operands of the color similarity test); GCodeFromSVG 1248 (arc whose sweep is exactly 0); DxfReader 60, 669 (spline with mismatched X/Y counts), 745 (`den == 0` in de Boor); SvgFilling 162 (operand combinations of the endpoint lookup); ImageTransform 508-510 (flood-fill color comparison per channel) |

### How the hard parts were reached

* Conversion errors: `GrblFile` runs the import on a thread that only logs
  exceptions; the case runner converts once on the test thread to record the
  exception in the golden (`error`), then loads through `GrblFile` as the app does.
* `SvgConverter.gcode` static state: restored from a snapshot before every case.
* Embedded resource branch: the accuracy test SVG embedded in LaserGRBL.exe.
* Centerline: only the conversion half (`convertFromText` with the centerline
  options), the autotrace step needs a Windows executable.
* `ParallelOptimizePaths` multi-task path: a list of 2050 paths (two blocks of 1025).
* Potrace raster filling: it draws into its own `new Bitmap`, which has 0 dpi on
  libgdiplus and made `ResizeImage` throw; the native shim gives every new bitmap
  96 dpi as on Windows (`native/lgshim.c`).
* Potrace arcs: Bezier pieces of 0.5 mm or less are exported as `G1`; the
  `potrace_disk_smooth` case uses 1 px/mm so the biarc (`G2`/`G3`) export runs.
* Image orientation: libgdiplus ignores pure flips on bitmaps drawn with a Graphics,
  which is every bitmap the raster pipeline hands to `LoadImageL2L`/`LoadImagePotrace`;
  the shim routes those flips through two working rotations (`native/lgshim.c`).
  Without it the `ip_*` goldens would be upside down compared with Windows.
* ImageProcessor: the generation (`DoTrueWork`) is called on the test thread for the
  golden cases; the white-box tests also run the real preview / generation threads
  (C# only) and wait on a C# probe of the static events (`ImageProcessorProbe`).
* Centerline: `autotrace.exe` is replaced by a shell double. `GrblCore.ExePath`
  needs a command line, which the pythonnet host does not have: the harness sets
  argv[0] with `mono_runtime_set_main_args` for the duration of the test, pointing
  at a temp folder that holds `Autotrace/autotrace.exe` (Mono turns the backslash of
  `Autotrace\autotrace.exe` into `/`). The double records the command line and the
  png, then prints a canned svg.

