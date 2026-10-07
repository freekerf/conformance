# Large files: LaserGRBL and FreeKerf on the same raster

`scripts/large_file.py` writes the synthetic raster of FreeKerf's benchmark
(`crates/core/freekerf-gcode/benches/analysis.rs`: `G90`, `M4`, then rows of one `G0`
and 499 `G1 X.. S..`, `M5`), analyzes it with both hosts and compares every field of
the golden JSON (`commands`, `wire`, `stream`, `offsets_s`, `estimated_time_s`, ranges,
quadrant).

```bash
make build                                   # LaserGRBL with Mono, once
FREEKERF_BIN=/path/to/release/freekerf uv run python scripts/large_file.py 100000 3
```

## Result (2026-10-07)

Machine: Intel Core i5-1235U (10 cores, 12 threads), Linux, Mono 6.8.0.105 (LaserGRBL
bf15096, Debug build of the harness), FreeKerf `main` plus freekerf#9, #10, #12 and #13,
Rust 1.97.1, `--release`.

**100,003 lines (1.3 MB): every field is equal**, the 100,005-line `stream` included
(estimated time 99.102 s on both).

| Measurement | 100k lines | 1M lines |
| --- | ---: | ---: |
| LaserGRBL: `GrblFile.LoadFile` (load + analysis, in process), best of 3 | 0.41 s | 3.96 s |
| FreeKerf: `freekerf analyze --json` (process: parse, analysis, simulated job run for `stream`, JSON), best of 3 | 0.24 s | 2.59 s |
| FreeKerf: parse + analysis only (`cargo bench -p freekerf-gcode`, rayon) | — | 0.358 s |
| FreeKerf: parse + analysis only, sequential (`--no-default-features`) | — | 0.504 s |
| Harness: `golden.analyze_csharp` (load, analysis and streaming the job through the Python fake device) | 407 s | not run |

Notes:

* The comparable pair is LaserGRBL's load + analysis against FreeKerf's parse +
  analysis: 3.96 s against 0.36 s (rayon) or 0.50 s (one thread) for 1M lines.
  `freekerf analyze --json` also simulates the whole job run against its emulator
  to produce `stream` (most of its 2.59 s) and still takes less than LaserGRBL's
  load alone.
* The C# numbers are Mono on Linux, not .NET Framework on Windows; treat them as an
  order of magnitude. The 407 s of the golden analyzer are the harness (one Python
  device round trip per line), not LaserGRBL.
* FreeKerf's `doc/benchmarks.md` records 0.67 s (rayon) and 0.93 s (sequential) for
  the same benchmark on a 4 vCPU cloud container; this machine is faster (0.36 s and
  0.50 s). The ratio rayon/sequential is similar (0.71 here, 0.72 there).
