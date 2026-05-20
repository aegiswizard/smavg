# 2026-05-09 Single-File Container v1 Benchmark

This benchmark validates `project.smavg`, the first compact single-file Smavg
container. It uses Planner v1, real input files, byte-perfect verification, and
independent restored-directory diffs.

Container layout:

```text
fixed header
compressed JSON manifest
concatenated payload region
```

The manifest stores family/fallback offsets, sizes, hashes, and planner report
metadata. History member paths and hashes remain inside the self-verifying
history-pack payloads.

## Luau Versioned History

Source:
`/tmp/smavg-archive-v1-luau/corpus/records`

Command:

```bash
PYTHONPATH=src python3 -m smavg.cli pack /tmp/smavg-archive-v1-luau/corpus/records --out /tmp/smavg-luau-planner.smavg
PYTHONPATH=src python3 -m smavg.cli verify /tmp/smavg-luau-planner.smavg
PYTHONPATH=src python3 -m smavg.cli restore /tmp/smavg-luau-planner.smavg /tmp/smavg-container-luau-restored
diff -qr /tmp/smavg-archive-v1-luau/corpus/records /tmp/smavg-container-luau-restored
```

Measured output:

- Files: 1,547
- Logical/source apparent bytes: 171,156,036
- Archive bytes: 312,080
- Payload bytes: 311,184
- Manifest bytes: 808
- Header bytes: 88
- Overhead bytes: 896
- Ratio: 548.436x
- Payload ratio: 550.016x
- Families: 1 `history_pack`, 1,547 files
- Fallback files: 0
- Archive verify: PASS
- Restore: 1,547 files
- `diff -qr` restored vs source: PASS

Baselines:

| Method | Bytes | Source ratio |
| --- | ---: | ---: |
| Smavg `.smavg` container | 312,080 | 548.436x |
| `tar | xz -9e` | 373,832 | 457.842x |
| `tar | zstd -19 --long=31` | 392,880 | 435.645x |
| `tar | brotli -q 11` | 485,571 | 352.484x |

## Mixed Real Corpus

Source:
`/tmp/smavg-planner-mixed/source`

Corpus composition:

- 323 real Luau historical versions of `Analysis/src/ConstraintSolver.cpp`.
- 296 real Luau historical versions of `Analysis/src/Frontend.cpp`.
- Five real Smavg project files.
- One real `/bin/ls` system binary.

Command:

```bash
PYTHONPATH=src python3 -m smavg.cli pack /tmp/smavg-planner-mixed/source --out /tmp/smavg-planner-mixed.smavg
PYTHONPATH=src python3 -m smavg.cli verify /tmp/smavg-planner-mixed.smavg
PYTHONPATH=src python3 -m smavg.cli restore /tmp/smavg-planner-mixed.smavg /tmp/smavg-container-mixed-restored
diff -qr /tmp/smavg-planner-mixed/source /tmp/smavg-container-mixed-restored
```

Measured output:

- Files: 625
- Logical/source apparent bytes: 46,885,286
- Archive bytes: 177,025
- Payload bytes: 175,332
- Manifest bytes: 1,605
- Header bytes: 88
- Overhead bytes: 1,693
- Ratio: 264.851x
- Payload ratio: 267.409x
- Families: 2 `history_pack` families, 619 files
- Fallback files: 6 in `full_zlib`
- Archive verify: PASS
- Restore: 625 files
- `diff -qr` restored vs source: PASS

Baselines:

| Method | Bytes | Source ratio |
| --- | ---: | ---: |
| Smavg `.smavg` container | 177,025 | 264.851x |
| `tar | xz -9e` | 178,308 | 262.945x |
| `tar | zstd -19 --long=31` | 187,012 | 250.707x |
| `tar | brotli -q 11` | 193,676 | 242.081x |

## Interpretation

Container v1 solves the Planner v1 metadata-overhead problem for the measured
mixed corpus. The directory store had a better debugging model but a
216,975-byte total store because SQLite and JSON metadata were visible on a
small archive. The single-file container reduces total size to 177,025 bytes,
beating the measured `xz` baseline while preserving the same byte-perfect
restore behavior.
