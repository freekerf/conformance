# Scope: what "the core" is

The core is the part of LaserGRBL that a Rust rewrite has to reproduce exactly:
G-code parsing and analysis, the Grbl protocol state machine (streaming, buffer
accounting, responses, status reports, overrides, jog, configuration), the firmware
variants, persistence of settings, and the built-in emulator. The machine-readable
version of this list is [`scope.toml`](scope.toml); the coverage report is filtered
with it.

Validated by reading the code (bf15096). Line ranges are inclusive.

## Tier "core" (target: 100 % lines and branches, net of justified exclusions)

| File | What is in scope | Notes |
|------|------------------|-------|
| `LaserGRBL/Core/GrblCore.cs` | whole file: `GrblCore` (connection, TX/RX loops, streaming modes, buffer accounting, response/status parsing, vendor detection, overrides, jog, continuous jog, config `$$`/`$I`, Wi-Fi config, job lifecycle, resume, custom code + expressions, auto cooling, permissions), `TimeProjection`, `GrblConfST`, `GrblConf` (obsolete format), `GrblVersionInfo`, `GPoint`, `LaserLifeHandler` | The UI glue inside this file (file dialogs, message boxes, resume/position dialogs, WMI lookup) is excluded line by line in `exclusions.toml` |
| `LaserGRBL/Core/MarlinCore.cs` | whole file | |
| `LaserGRBL/Core/SmoothieCore.cs` | whole file | |
| `LaserGRBL/Core/VigoCore.cs` | whole file | |
| `LaserGRBL/GrblCommand.cs` | whole file: `GrblCommand`, `GrblMessage`, `CSVD`, `IGrblRow` | |
| `LaserGRBL/StateBuilder.cs` | whole file: `StateBuilder`, `StatePositionBuilder`, `G2G3Helper`, `JogCommand` | |
| `LaserGRBL/Settings.cs` | whole file | static store persisted with BinaryFormatter |
| `LaserGRBL/GrblFile.cs` | lines 24-174 (class, load, clear, save), 366-377 (`CheckInUse`), 507-518 (events), 1321-1353 (`Count`, `EstimatedTime`, `Quadrant`, `formatnumber`), 1470-1498 (`Analyze`), 1684-1850 (enumeration, `ProgramRange`) | raster/vector generation is phase 2 (below) |
| `LaserGRBL/GrblEmulator/Grblv11Emulator.cs` | whole file | used by the "Emulator" connection type |
| `LaserGRBL/ComWrapper/Emulator.cs` | whole file | `IComWrapper` for the emulator |
| `LaserGRBL/ComWrapper/UsbSerial.cs` | whole file | the default serial transport; exercised over a PTY |
| `LaserGRBL/Tools/RetainedSetting.cs` | whole file | used by `GrblCore` properties |
| `LaserGRBL/Tools/MathHelper.cs` | lines 14-24 (`MathHelper.LinearDistance`) | `RulerStepCalculator` belongs to the UI rulers |

`ComWrapper/IComWrapper.cs` is in scope as the transport contract but has no
executable code (interface + enum); the tests implement it (`tools/TestSupport.cs`).

`GrblConfig.cs` was in the initial list: it turned out to be only the WinForms
settings dialog (`GrblConfig : Form`); the non-UI configuration (`GrblConfST`)
lives in `GrblCore.cs` and is covered there.

## Tier "helper" (measured, no target)

Code the core calls into but that is infrastructure or embedded third-party code.
It is exercised through the core tests and reported for information.

| File | Why not "core" |
|------|----------------|
| `LaserGRBL/Tools/ExpressionEvaluator.cs` | third-party (CodeProject, J. Roberts 2004); only `[expr]` evaluation in custom code is core behaviour, and that is tested through `GrblCore.EvaluateExpression` |
| `LaserGRBL/Tools/Cronometro.cs` | timers (`ElapsedFromEvent`, `PeriodicEventTimer`) |
| `LaserGRBL/Tools/ThreadClass.cs` | worker-thread wrapper used for the TX/RX loops |
| `LaserGRBL/CSV/CsvDictionary.cs` | CSV lookup for error/alarm/setting descriptions |

## Out of scope

* WinForms forms and controls (everything deriving from `Form`/`Control`,
  `HotKeysManager` UI glue, `PreviewForm`, `JogForm`, ...).
* Embedded third-party libraries: `SharpGL`, `SvgLibrary`, `Clipper`, `CsPotrace`,
  `ComWrapper/RJCP`, `WebSocket`, `ComWrapper/MySerial` (a copy of Mono's serial code).
* Other transports: `UsbSerial2`, `RJCPSerial`, `Telnet`, `LaserWebESP8266`,
  `GrblEmulator/WebsocketEmulator.cs` (only their selection by `GrblCore.Configure`
  is tested). They are thin adapters over third-party stacks; add them to the
  protocol layer if the Rust version keeps them.
* `Tools/HiResTimer.cs`: Win32 timer P/Invokes, replaced by a native shim in this
  harness (`native/lgshim.c`); semantics are "monotonic milliseconds".
* `Logger`, `ComLogger`, `Telegram`, `UsageStats`, `UrlManager`, `Tools/Serializer.cs`,
  `Tools/Project.cs` (used by the core, not part of its behaviour).

## Tier "importers" (phase 2; same target, reported separately)

G-code generators and the SVG/DXF/raster importers: input file (or pixels, or
parameters) + options -> G-code. Characterized mostly with golden cases
(`fixtures/importers/cases/*.json` -> `fixtures/golden/importers/*.json`, format in
`src/lasergrbl_harness/importers.py`), plus white-box tests in `tests/importers/`.

| File | What is in scope | Notes |
|------|------------------|-------|
| `LaserGRBL/GrblFile.cs` | 175-216 (`LoadImportedSVG`/`LoadImportedVector`), 218-365 (Line2Line color segments, filling predicates), 519-1320 (`L2LConf`, `LoadImageL2L`, cutting / power-speed / shake test generators, Line2Line segmentation and optimization, path ordering, pixel helpers) | the G-code part of the file stays in tier "core" |
| `LaserGRBL/Hershey/Hershey.cs` | whole file | vector font of the test generators; the golden cases pin the whole font table |
| `LaserGRBL/SvgConverter/GCodeFromSVG.cs` | whole file | SVG parser and G-code writer (also the conversion half of Centerline) |
| `LaserGRBL/SvgConverter/gcodeRelated.cs` | whole file | static G-code writer shared by SVG and DXF |
| `LaserGRBL/SvgConverter/SvgColorLayer.cs`, `SvgFilling.cs`, `VectorImportSource.cs`, `VectorDrawing.cs`, `VectorGCode.cs` | whole files | color layers, hatch filling, the import sources used by the color layers dialog |
| `LaserGRBL/SvgConverter/DxfReader.cs`, `ArcFitter.cs`, `BezierTools.cs` | whole files | DXF reader (lines, true arcs, blocks, splines -> arcs), curve helpers |
| `LaserGRBL/RasterConverter/ImageTransform.cs` | whole file | grayscale, threshold, invert, dithering, whitenize, resize, flood fill / outline |

Helper tier additions (third-party code used by the importers, measured only):
`RasterConverter/Dithering/ErrorDiffusionDithering.cs`, `RandomDithering.cs`,
`ImageUtilities.cs` (Cyotek, MIT) and `CsPotrace/PotraceClipper.cs` (Clipper-based
hatch filling).

What a golden case covers and what it does not:

* Generators, Hershey, SVG, DXF and Line2Line work on numbers and text only
  (`Bitmap.GetPixel` for raster): their goldens are portable as they are.
* Cases that draw through GDI+ (`Graphics.DrawImage` with a `ColorMatrix`, a
  threshold or an interpolation mode: grayscale, threshold, invert, resize) are
  marked `platform_dependent`: they were recorded with Mono's libgdiplus and are
  expected to differ by rounding (resize: by algorithm) on Windows GDI+.
* A new in-memory `Bitmap` has 96 dpi on Windows and 0 dpi on libgdiplus, where
  `ImageTransform.ResizeImage` throws; the harness creates its bitmaps with 96 dpi.
* `SvgConverter.gcode` is a static class whose firmware type is read once by its
  static constructor: every case starts from a snapshot of a fresh process
  (`importers.reset_gcode_statics`, see FINDINGS F-38).

## Still missing (next steps)

* `GrblFile.cs` 379-506 `LoadImagePotrace` (vectorization through CsPotrace; the
  Line2Line raster filling inside it is already covered through `LoadImageL2L`).
* `GrblFile.cs` 1421-1468 `LoadImageCenterline`: needs the Windows `autotrace.exe`;
  only its conversion half (`GCodeFromSVG.convertFromText` with the centerline
  options) is covered, as golden `svgtext_*`.
* `RasterConverter/ImageProcessor.cs` (the pipeline behind the raster dialog: resize,
  crop, rotation, thresholds, preview thread) and `GetVectorQuality`.
* `GrblFile.cs` 1355-1420 / 1500-1683 preview drawing (GDI, UI) and
  `Generator/*` / `SvgConverter/*Form*` / `RasterConverter/*Form*` dialogs (UI; the
  values they pass are the golden parameters).
* Raster/SVG/DXF entry points in `GrblCore.OpenFile` (open dialogs before importing).
