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
| `LaserGRBL/GrblFile.cs` | 175-216 (`LoadImportedSVG`/`LoadImportedVector`), 218-365 (Line2Line color segments, filling predicates), 379-506 (`LoadImagePotrace`: vectorize, with vector or raster filling), 519-1320 (`L2LConf`, `LoadImageL2L`, cutting / power-speed / shake test generators, Line2Line segmentation and optimization, path ordering, pixel helpers), 1421-1468 (`LoadImageCenterline`) | the G-code part of the file stays in tier "core" |
| `LaserGRBL/Hershey/Hershey.cs` | whole file | vector font of the test generators; the golden cases pin the whole font table |
| `LaserGRBL/SvgConverter/GCodeFromSVG.cs` | whole file | SVG parser and G-code writer (also the conversion half of Centerline) |
| `LaserGRBL/SvgConverter/gcodeRelated.cs` | whole file | static G-code writer shared by SVG and DXF |
| `LaserGRBL/SvgConverter/SvgColorLayer.cs`, `SvgFilling.cs`, `VectorImportSource.cs`, `VectorDrawing.cs`, `VectorGCode.cs` | whole files | color layers, hatch filling, the import sources used by the color layers dialog |
| `LaserGRBL/SvgConverter/DxfReader.cs`, `ArcFitter.cs`, `BezierTools.cs` | whole files | DXF reader (lines, true arcs, blocks, splines -> arcs), curve helpers |
| `LaserGRBL/RasterConverter/ImageTransform.cs` | whole file | grayscale, threshold, invert, dithering, whitenize, resize, flood fill / outline |
| `LaserGRBL/RasterConverter/ImageProcessor.cs` | all but the preview drawing (945-991, 1129-1135, 1166-1346) | the raster dialog pipeline: image edits (crop, auto trim, rotate, flip, invert, fill, outline, revert), the bitmap produced per tool, resolution choice (quality, adaptive vector quality, file dpi), `L2LConf` mapping, preview / generation threads |
| `LaserGRBL/Autotrace/Autotrace.cs` | whole file | wrapper around `autotrace.exe` (temp png, command line, stdout); the executable is a test double, see below |

Helper tier additions (third-party code used by the importers, measured only):
`RasterConverter/Dithering/ErrorDiffusionDithering.cs`, `RandomDithering.cs`,
`ImageUtilities.cs` (Cyotek, MIT), `CsPotrace/PotraceClipper.cs` (Clipper-based
hatch filling), `CsPotrace/CsPotrace.cs`, `CsPotraceExport.cs`,
`CsPotraceExportGCODE.cs` and `CsPotrace/BezierToBiarc/*` (potrace port and the
Bezier -> G2/G3 biarc export). CsPotrace is not chased line by line: its safety net
are the `potrace_*` golden cases (traced borders, holes, spot removal, smoothing
with arcs, corners, vector and raster filling, PWM on/off).

What a golden case covers and what it does not:

* Generators, Hershey, SVG, DXF and Line2Line work on numbers and text only
  (`Bitmap.GetPixel` for raster): their goldens are portable as they are.
* Cases that draw through GDI+ (`Graphics.DrawImage` with a `ColorMatrix`, a
  threshold or an interpolation mode: grayscale, threshold, invert, resize) are
  marked `platform_dependent`: they were recorded with Mono's libgdiplus and are
  expected to differ by rounding (resize: by algorithm) on Windows GDI+.
* A new in-memory `Bitmap` has 96 dpi on Windows and 0 dpi on libgdiplus, where
  `ImageTransform.ResizeImage` throws; the native shim gives every new bitmap 96 dpi.
* libgdiplus ignores pure flips (`RotateNoneFlipX/Y`) on bitmaps that were drawn with
  a Graphics; the shim performs them as rotation+flip pairs, as Windows does them.
* Vectorize with raster filling draws the traced shapes through GDI+ (antialiased
  fill + bicubic resize) before Line2Line: `potrace_raster_fill*` are
  `platform_dependent`. Borders and vector filling are pure numbers.
* `image_processor` cases run the whole dialog pipeline, which always resizes and
  converts to gray through GDI+: they are `platform_dependent`. What is portable is
  the composition, pinned by `test_imp_processor.py` (the bitmap per tool equals a
  documented chain of `ImageTransform` calls with the dialog values mapped as
  `Red/100`, `-(100-Brightness)/100`, `Contrast/100`, `Threshold/100`, white clip).
* Centerline runs the external `autotrace.exe` (Windows binary, not run here). A
  shell double records the command line and the png LaserGRBL gives it and prints a
  canned svg: `centerline_*` pin the command line (`-centerline`, `-corner-t`,
  `-line-t <value/10>`), the input bitmap and the conversion of the svg with the
  dialog settings. The autotrace algorithm itself is not characterized: a port
  that keeps autotrace keeps its output; one that replaces it needs its own tests.
* `SvgConverter.gcode` is a static class whose firmware type is read once by its
  static constructor: every case starts from a snapshot of a fresh process
  (`importers.reset_gcode_statics`, see FINDINGS F-38).

## Not covered (decided)

* The autotrace algorithm (external executable, see above).
* `ImageProcessor` preview drawing (line overlays, vector preview, centerline preview,
  white point demo) and `GrblFile.cs` 1355-1420 / 1500-1683 preview drawing (GDI, UI) and
  `Generator/*` / `SvgConverter/*Form*` / `RasterConverter/*Form*` dialogs (UI; the
  values they pass are the golden parameters).
* Raster/SVG/DXF entry points in `GrblCore.OpenFile`: decided not to test (glue
  that opens a dialog per file type). What they do, for the port:

  | Extension (lower-cased, `GrblCore.cs:666-668`) | Goes to |
  |-----------|---------|
  | `.nc`, `.cnc`, `.tap`, `.gcode`, `.ngc` | `GrblFile.LoadFile` (G-code, tier core) |
  | `.bmp`, `.png`, `.jpg`, `.jpeg`, `.gif` | raster dialog (`RasterToLaserForm` -> `ImageProcessor`) -> `LoadImageL2L` / `LoadImagePotrace` / `LoadImageCenterline` |
  | `.svg` | `SvgToGCodeForm` -> `LoadImportedSVG` / `LoadImportedVector` (the "SVG as raster" branch, `GrblCore.cs:733-765`, is dead: the mode is hard-coded to Vector) |
  | `.dxf` | `DxfReader.Read` -> `SvgToGCodeForm` with a `DxfImportSource` -> `LoadImportedVector`; `DxfImportException` and other errors are shown in a MessageBox |
  | `.lps` (project) | for each stored image: write it to the temp dir, restore its saved settings, then `ReOpenFile` (first) / `OpenFile(append)` (others) |
  | anything else | MessageBox "unsupported file type", nothing loaded |
