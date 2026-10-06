# Findings

Behaviour of the current C# core that looks like a bug or is surprising. Nothing
was fixed: the characterization tests pin the **current** behaviour. Each entry
names the test(s) that would change if the behaviour were fixed, so the Rust
rewrite can decide consciously whether to replicate it.

Line numbers refer to bf15096. Severity is a rough guess of user impact.

## Protocol / streaming

| id | where | finding | sev. | pinned by |
|----|-------|---------|------|-----------|
| F-30 | `Core/GrblCore.cs:1068-1072, 1123-1126` (and `961-965, 1006-1010` for `$I`) | The connect-time `RefreshConfig`/`RefreshMachineInfo` (a thread-pool work item started 500 ms after connecting) swap `mQueuePtr`/`mSentPtr` to private lists while they wait for `$$`/`$I`. A job or manual command started in that window is enqueued into the private queue and whatever was not sent yet is dropped when the `finally` restores the pointers; the job then stays "in program" forever (no lines left, never ends). `CanSendFile` only checks the real queue. Observed live while building the protocol tests (a job right after connecting streamed nothing). | high | `test_core_tx.py::test_job_started_during_connect_time_refresh_is_lost`; protocol tests wait for `HostAdapter.ready` |
| F-28 | `Core/GrblCore.cs:1076-1080, 969-973` | When `$$`/`$I` gets no answer in 10 s, `TimeoutException` is thrown but the unanswered command stays in `mPending` with its bytes counted in `mUsedBuffer`: the next `ok` from the board is matched to it, shifting every later response by one. | medium | `test_core_live.py::test_refresh_config_times_out_after_10s_without_answer`, `..._machine_info_...` |
| F-29 | `Core/GrblCore.cs:1294-1295, 1249-1250` | `WriteConfig` and the Ortur Wi-Fi write busy-wait with an empty loop body (`while (...) ;`): no sleep (spins a core) and no timeout (blocks the caller forever if the board never answers). | medium | observed; the tests use a PTY link so the device keeps answering while the caller blocks |
| F-24 | `Core/GrblCore.cs:1279-1281, 1053-1056` | `WriteConfig` and `RefreshConfig` silently do nothing unless the machine is Idle/Alarm and not in a program: no exception, no return value. A transient `Run` in the last status report is enough to drop a settings write. | medium | `test_core_tx.py::test_write_config_is_silently_skipped_when_not_idle` |
| F-17 | `GrblCommand.cs:202-245` + `Core/GrblCore.cs` `SendLine` | `BuildHelper` (called at send time and during file analysis) rewrites the command text, removing comments. Comment-only lines are kept as commands and streamed as empty lines (`"\n"`), each costing an `ok` round trip. The default "passes" code is four comment lines, so every pass between loops sends four empty lines. | low | `test_core_tx.py::test_loop_count_repeats_program_with_passes_code`, `test_grblfile.py::test_load_skips_blank_lines_and_keeps_comment_lines`, golden `comments_spacing.json` |
| F-20 | `Core/GrblCore.cs:1620-1621` | `SafetyDoor()` sends `'@'` (0x40), the Grbl 0.9 safety-door character. Grbl 1.1 uses 0x84 and treats `@` as a normal character, which ends up prefixed to the next line. | medium | `test_core_tx.py::test_safety_door_sends_legacy_at_sign` |
| F-19 | `Core/GrblCore.cs:1475` | Job resume enqueues `new GrblCommand(spb.GetSettledModals())` even when no modal group is settled, i.e. an empty command (streamed as an empty line). | low | `test_core_tx.py::test_resume_with_homing_and_work_offset` |
| F-15 | `Core/GrblCore.cs:2610-2620, 2654-2664` | A status report containing `|` and `Pin:` while the firmware version is still unknown is "guessed" as Grbl 1.0c and parsed with the legacy comma parser, which fails on `Idle|MPos`; the error is swallowed and nothing (state, position) is updated. | low | `test_core_rx.py::test_pin_report_with_unknown_version_is_not_parsed` |
| F-16 | `Core/GrblCore.cs:2816-2817` with `467-480` | After a successful `$N=V` write the core updates `GrblCore.Configuration`, but the getter returns a *new default object* when no configuration was read yet, so the update is lost; when one exists it is mutated in place without triggering a settings save. | low | `test_core_rx.py::test_eeprom_write_is_lost_when_no_configuration_was_read_yet`, `..._updates_stored_configuration` |
| F-08 | `Core/VigoCore.cs:126-134` | Outside a Vigo job, `SendToSerial` marks the command `ok` itself but leaves it in `mPending` (and does not count its bytes): pending grows by one per command and later board responses are matched to stale commands. | medium (Vigo only) | `test_variants.py::test_vigo_outside_job_marks_commands_ok_immediately` |
| F-21 | `Core/GrblCore.cs:1848-1919` (`EnqueueJogV09`/`V11`, `HandleContinuosJog`) | Jog feed `F{speed}` is formatted with the current culture (float interpolation): on comma-decimal locales a fractional speed becomes `F1234,5`, which Grbl rejects. Steps and positions use the invariant culture. | low (integer speeds in the UI) | `test_core_jog.py::test_jog_feed_uses_current_culture` |
| F-22 | `Core/GrblCore.cs:1860-1870, 1906-1916` | Jog steps are formatted with `"0.0"`: 0.25 mm becomes 0.3 and 0.04 mm becomes 0.0 (a zero-length jog). | low | `test_core_jog.py::test_jog_step_is_rounded_to_one_decimal` |

## G-code parsing and analysis

| id | where | finding | sev. | pinned by |
|----|-------|---------|------|-----------|
| F-01 | `GrblCommand.cs:193-248` | `BuildHelper` swallows parse errors (`catch { }`): with `X1..5` or a repeated letter (`G90 G1 X3`, very common in real files) every word after the error is silently dropped, so the analysis (position, time, bbox) ignores them, while the line is still streamed unchanged to the board, which interprets all of it (`G90 G1 X3` moves; `X1..5` is rejected with an error). | high (analysis differs from what the machine does) | `test_grblcommand.py::test_unparseable_number_stops_parsing_silently`, `..._repeated_letter_...`, golden `malformed.json` |
| F-18 | `StateBuilder.cs:308, 325-342` | The units modal group (G20/G21) exists but is never updated: inch programs are analyzed as millimetres (time, bounding box), and job resume does not restore G20. | medium | `test_core_tx.py::test_resume_from_position_rebuilds_state`, golden `inches.json` |
| F-12 | `StateBuilder.cs:404-408` | For `G2/G3 ... R`, the arc center is always the chord midpoint and `R` is ignored: radius, length (time) and bounding box are only right for half circles. | medium | `test_statebuilder.py::test_r_arc_assumes_center_at_chord_midpoint`, golden `arcs.json` |
| F-02 | `GrblCommand.cs:266-267` | `Clone()` is `MemberwiseClone`: the clone shares the private result holder (and the parsed helper). The job queue holds clones of the file's commands, so results set during the run show on the file's rows. | low (may be intended for the UI) | `test_grblcommand.py::test_clone_shares_result_wrapper` |
| F-04 | `GrblCommand.cs:209-239` | Removing an inline comment keeps the spaces on both sides (`X1 (c) Y2` -> `X1  Y2`). Cosmetic, but visible in saved/normalized text. | low | `test_grblcommand.py::test_build_helper_collapses_spaces_and_strips_comments` |
| F-03 | `GrblCommand.cs:553-561` | Decoding an unknown `ALARM:N` sets the message text to `null` (the CSV lookup result is assigned unconditionally). | low | `test_grblcommand.py::test_message_unknown_alarm_decodes_to_none` |
| — | `StateBuilder.cs` (all `TimeSpan.From*`) | Not a bug but important for a port: .NET Framework's `TimeSpan.FromMinutes/FromSeconds` round to whole milliseconds, so every per-command time estimate is quantized to 1 ms before being summed. | info | `test_statebuilder.py::test_time_estimates_are_rounded_to_milliseconds`, all golden `offsets_s` |

## Configuration, versions, settings

| id | where | finding | sev. | pinned by |
|----|-------|---------|------|-----------|
| F-13 | `Core/GrblCore.cs:3901-3908` | `GrblConfST.ReadDecimal` first parses invariantly; when that fails (e.g. `500.5 mm/min`) the regex fallback parses with the *current* culture, so `500.5` becomes 5005 on it-IT/pt-BR. | low | `test_core_types.py::test_conf_regex_fallback_parses_with_current_culture` |
| F-05 | `Core/GrblCore.cs:239-240` | `VendorName` compares `ToLower()` with `"Vigotec"`: never true, Vigotec boards report "Unknown". | low | `test_core_types.py::test_version_vendor_name_vigotec_is_never_detected` |
| F-09 | `Core/GrblCore.cs:230` | `IsLuckyWiFi` relies on `&&`/`||` precedence: `IsOrtur && ... || IsLonger && x == "Longer Nano" || mVendorInfo == "NanoDuo"`. Works for the known boards but probably not what was meant. | info | `test_core_types.py::test_version_vendor_flags` |
| F-10 | `Core/GrblCore.cs:625-631` | `RiseOnFileLoading` checks `OnFileLoaded != null` before invoking `OnFileLoading`: a subscriber of only `OnFileLoading` is never called. | low | `test_grblfile.py::test_file_loading_event_is_only_raised_when_loaded_has_subscribers` |
| F-11 | `Core/GrblCore.cs:816` | Opening a `.lps` project builds the temporary image path with a hard-coded `\\` separator (Windows only; on Linux the file name contains a backslash). | low (Windows app) | `test_core_gaps.py::test_project_file_restores_settings_and_opens_each_image` |
| F-14 | `Core/GrblCore.cs:3563-3564, 3675` | `TimeProjection.JobEnd(false)` (end of a pass in a multi-pass job) does not set `mGlobalEnd`, so `TotalGlobalJobTime` is negative until the next pass starts. | low | `test_core_types.py::test_time_projection_pauses_are_excluded_from_true_time` |

## Laser life counters

| id | where | finding | sev. | pinned by |
|----|-------|---------|------|-----------|
| F-26 | `Core/GrblCore.cs:4510` | `ComputeLaserTime` measures the run-time delta from the last *power* sample (`mLastPowerHiResTimeNano`) instead of the last status sample; the status timestamp is stored but never used. | low | `test_lifehandler.py::test_run_time_accumulates_only_in_run_state` |
| F-27 | `Core/GrblCore.cs:4698-4712` | The statistics upload builds `"Classes": { 0.000, ... }`: the payload is not valid JSON. | low | `test_lifehandler.py::test_upload_success_records_last_sent` |
| F-07 | `Core/GrblCore.cs:4563-4575` | `OnConnect`: the `death` list uses the same predicate as `alive`, and `if (Count == 0)` lacks an `else`, so with no counters the code falls through to the selector dialog. | low | `test_lifehandler.py::test_on_connect_without_counters_falls_through_to_dialog` |

## Emulator

| id | where | finding | sev. | pinned by |
|----|-------|---------|------|-----------|
| F-23 | `ComWrapper/Emulator.cs:39-50` | `Open()` lets the emulator send its banner and then clears the receive buffer, discarding it; the host only learns the version from the banner after its soft reset. | low | `test_emulator.py::test_emulator_wrapper_reads_and_close_states` |
| F-25 | `GrblEmulator/Grblv11Emulator.cs:205-207` | Status reports end with `\n` and `ImmediateTX` appends another one: an empty line follows every status (filtered by the wrapper). | info | `test_emulator.py::test_emulator_direct_api_with_sink` |

## Importers (phase 2)

| id | where | finding | sev. | pinned by |
|----|-------|---------|------|-----------|
| F-31 | `SvgConverter/GCodeFromSVG.cs:892-893` (args), `956-972` (`L`) | The path argument regex reads the valid compact number syntax `-4.5.5` (that is `-4.5` then `.5`, common in files written by svgo and other optimizers) as one number. A command then gets an odd number of arguments and `floatArgs[i + 1]` throws `IndexOutOfRangeException`: nothing of the file is imported (F-33). | high | golden `svg_compact_numbers` |
| F-32 | `SvgConverter/GCodeFromSVG.cs:754` | A `<path>` without a `d` attribute throws `NullReferenceException` (`Attribute("d").Value`): the whole import is lost (F-33). | medium | golden `svg_path_without_d` |
| F-33 | `GrblFile.cs:183-215` with `103-120` | `LoadImportedVector` clears the current file before converting and runs on a thread that only logs exceptions: when the conversion throws, the previous file is gone, `Analyze` and `OnFileLoaded` never run, and the user gets no message. | medium | `test_imp_svg.py::test_failed_import_clears_the_file_and_never_reports_loaded` |
| F-34 | `SvgConverter/GCodeFromSVG.cs:702`, `693-715` | `polyline`/`polygon` points: after the first pair, tokens of 3 characters or less (`9,9`) are silently skipped; a points list without commas (`30 50 40 58`) produces only a comment. | medium | golden `svg_basic_shapes` |
| F-35 | `SvgConverter/GCodeFromSVG.cs:1217-1221`, `1228-1258` | An arc with a zero radius is not drawn: `rx = ry = 0` returns early; with only one zero radius the scale factor is infinite, the segment count is NaN and the loop does nothing. The SVG spec draws a straight line; here the path continues from the old pen position (a gap). | low | golden `svg_paths` |
| F-36 | `SvgConverter/GCodeFromSVG.cs:430-440`, `531` | `skewX`/`skewY` transforms are silently ignored. A transform without the closing parenthesis (`translate(5,5`) loses its last character (`GetTextBetween` returns `Length - start - 1`). | low | golden `svg_transforms` |
| F-37 | `SvgConverter/GCodeFromSVG.cs:105` (`Resources/ResourceHelper.cs:12-14`) | Every file name starting with `LaserGRBL.` is read as an embedded resource: an existing file opened by such a *relative* name throws `ArgumentNullException`. (Used on purpose for the embedded accuracy test file; absolute paths from the dialogs are not affected.) | low | `test_imp_svg.py::test_relative_file_name_starting_with_laser_grbl_is_taken_as_a_resource`, golden `svg_embedded_accuracy_test` |
| F-38 | `SvgConverter/gcodeRelated.cs:57` | The SVG/DXF G-code writer reads "Firmware Type" once, in its static constructor: changing the firmware in the settings has no effect on SVG/DXF import until LaserGRBL is restarted (raster import reads it each time). | low | `test_imp_svg.py::test_firmware_type_is_read_once_per_process` |
| F-39 | `GrblFile.cs:644` | Cutting test label for a pass range reads `1 - F2 pass` (stray `F` before the last pass count). | low | golden `gen_cutting_grid` |
| F-40 | `Hershey/Hershey.cs:329` | Hershey text coordinates are formatted with `double.ToString()` after adding the offset: floating point noise reaches the G-code (`Y0.00299999999999989`, `X0.0460000000000003`). .NET Framework prints 15 significant digits ("G"); a port must reproduce that format to match the goldens, or round. | info | golden `hershey_*`, `gen_cutting_*`, `gen_greyscale_*` |
| F-41 | `RasterConverter/Dithering/ErrorDiffusionDithering.cs:89`, `72-73` | Error diffusion (all modes except Random) checks `offsetX > 0` and `offsetY > 0`: no error ever reaches row 0 or column 0 (a uniform mid-gray first row comes out all black). The blue and green errors are also swapped (no effect on gray images). Third-party code (Cyotek). | low | `test_imp_raster.py::test_error_diffusion_never_reaches_first_row_or_column`, golden `img_dither_*` |
| F-42 | `RasterConverter/Dithering/RandomDithering.cs:38` | Random dithering is seeded with `Environment.TickCount`: the same image gives a different engraving each time. | info | `test_imp_raster.py::test_random_dithering_keeps_black_and_white_and_outputs_only_pure_colors` |
| F-43 | `SvgConverter/SvgColorLayer.cs:88-104` | `LoadSettings` with a malformed saved value returns `false` but keeps the fields parsed before the error (e.g. the mode), so the dialog shows a half-loaded layer with default speed/power. | low | `test_imp_svg.py::test_layer_settings_missing_or_invalid` |
| F-44 | `SvgConverter/VectorGCode.cs:48`, `GCodeFromSVG.cs:146`, `gcodeRelated.cs:173-191` | Like F-17: every layer pass starts with a comment-only line (`(Layer #000000 Line pass 1/1)`), kept as an empty command and streamed as an empty line; pen up/down commands carry a comment, leaving a trailing space (`S0 `). | low | every `svg_*`/`dxf_*` golden |
| — | `GrblFile.cs:546` (and `387`) | `LoadImageL2L` and `LoadImagePotrace` flip the caller's `Bitmap` in place (`RotateFlip`). The raster dialog passes a temporary bitmap, so it is harmless today. | info | `test_imp_raster.py::test_l2l_flips_the_bitmap_it_is_given`, `test_imp_potrace.py::test_flips_the_bitmap_it_is_given` |
| — | `SvgConverter/BezierTools.cs:80-99` | Curve flattening tests flatness as `sqrt(triangle area) < error` (not a distance) and emits the 4 control points of every sub-curve flat enough: the polyline goes through off-curve points (within the tolerance). Worth knowing to reproduce the goldens exactly. | info | `test_imp_vector.py::test_flatten_emits_the_control_points_of_flat_curves` |
| F-45 | `GrblFile.cs:397-400` | Vectorize options that are unchecked in the dialog are not "off": spot removal falls back to turdsize 2 (shapes of up to 2 px are still dropped) and unchecked optimization keeps tolerance 0.2 with curve optimization disabled. | info | `test_imp_potrace.py::test_disabled_options_set_potrace_defaults` |
| F-46 | `GrblFile.cs:423-428`, `443-449` | In vectorize with raster filling, the filling header follows `L2LConf.pwm` while the borders follow the "Support Hardware PWM" setting: with the two out of sync the job mixes `M5 S<max>`/`M3` switching (filling) and `S` power switching (borders). | low | golden `potrace_raster_fill_no_pwm` |
| F-47 | `GrblFile.cs:433` | The raster filling inside `LoadImagePotrace` sets `c.vectorfilling = true` on the caller's `L2LConf` (side effect, like the bitmap flip). | info | `test_imp_potrace.py::test_raster_filling_sets_vectorfilling_on_the_callers_conf` |
| — | `CsPotrace/CsPotrace.cs:1679, 1708`, `122-153` | Potrace keeps the bitmap, the path list and its options in static fields: two vectorizations at the same time would corrupt each other (today the UI runs one at a time). A port should make them per call. | info | — |
| F-48 | `GrblFile.cs:1436-1450`, `Autotrace/Autotrace.cs:71-88` | When autotrace fails (missing or blocked `autotrace.exe`, crash) the exception is only logged and the empty output is parsed as SVG: the user gets "Root element is missing" (XmlException) instead of the cause. The file was already cleared and `OnFileLoading` raised, `OnFileLoaded` never comes. | low | `test_imp_centerline.py::test_without_autotrace_the_empty_output_fails_as_xml`, `test_autotrace_printing_nothing_fails_the_same_way` |
| F-49 | `GrblFile.cs:1443-1449`, `SvgConverter/gcodeRelated.cs:62-80` | Centerline ignores the `L2LConf` it receives: speed, power, laser commands and offset are read back from the raster dialog settings (`RasterToLaserForm.StoreSettings` writes them just before generating), and the SVG size is `max(width, height) / 10` mm, i.e. it assumes the 10 px/mm that `ImageProcessor` forces for this tool. Works in the app, but the coupling is invisible from the call. | info | golden `centerline_settings`, `ip_centerline` |
| F-50 | `RasterConverter/ImageProcessor.cs:160-175` | "Is gray scale" samples one pixel every 10 in each direction, with a tolerance of 20 between channels: a gray image with color details off that grid counts as gray, and then the selected formula and RGB weights are ignored (SimpleAverage). | info | `test_imp_processor.py::test_gray_detection_samples_every_tenth_pixel`, golden `ip_gray_image_ignores_formula` |
| — | (platform) `GrblFile.cs:387, 546`, `ImageProcessor.cs:398, 415` | libgdiplus ignores `RotateNoneFlipX/Y` on a bitmap a Graphics was ever created for (every bitmap `ImageTransform` draws, and `new Bitmap(Image)`): on Mono, raster/vectorize jobs from the dialog would be engraved upside down and the dialog's flip buttons would do nothing. | info (Mono only) | harness: `native/lgshim.c` performs those flips as rotation+flip pairs; golden `ip_orientation` |
| — | (platform) `RasterConverter/ImageTransform.cs:31` | `ResizeImage` copies the source resolution with `SetResolution`; a `Bitmap` created in memory has 0 dpi on Mono's libgdiplus (96 on Windows) and that call throws there, e.g. in the Potrace raster filling (`GrblFile.cs:421`, its own `new Bitmap`). | info (Mono only) | harness: `native/lgshim.c` gives every new `Bitmap` 96 dpi, as on Windows |

## Other notes (expected behaviour worth preserving consciously)

* `$$`/`$I` replies are collected until 500 ms after the last received line (5 s
  max). Data arriving later is logged as plain messages and the configuration is
  left as it was (`test_core_gaps.py::test_settings_arriving_after_500ms_are_missed`).
* Comments are never sent to the board, but comment-only lines are (as empty lines, F-17).
* `GrblFile.SaveGCODE(..., useLFLineEndings=false)` uses `Environment.NewLine`:
  CRLF on Windows, LF on Linux/Mono.
* Grbl 1.1 boards advertise `[OPT:V,15,128]` (and `Bf:..,128` when idle): the core
  then uses a 128-byte budget instead of the default 127 (protocol test
  `test_stream_uses_128_bytes_when_grbl_reports_it`).
