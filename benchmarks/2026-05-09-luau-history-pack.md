# 2026-05-09 Luau History-Pack Benchmark

This benchmark uses real historical file versions extracted from the local
`/Users/mac/luau` Git repository. It is not synthetic and does not use mocked
data.

## Corpus

- Source: `/tmp/smavg-archive-v1-luau/corpus/records`
- Files: 1,547 exact historical versions
- Logical/apparent source bytes: 171,156,036
- Source disk bytes: 174,338,048
- File histories:
  - `tests/TypeInfer.tables.test.cpp`
  - `Analysis/src/ConstraintSolver.cpp`
  - `tests/Conformance.test.cpp`
  - `Analysis/src/TypeInfer.cpp`
  - `Analysis/src/Frontend.cpp`

## Smavg Result

Command:

```bash
PYTHONPATH=src python3 -m smavg.cli --store /tmp/smavg-history-pack-store archive /tmp/smavg-archive-v1-luau/corpus/records --snapshot-id luau-history-pack
```

Measured output:

- Store apparent bytes: 334,460
- Store disk bytes: 344,064
- Payload bytes: 311,184
- SQLite metadata bytes: 22,528
- Snapshot manifest bytes: 541
- Config bytes: 207
- Apparent ratio: 511.738x
- Disk ratio: 497.454x
- Payload ratio: 550.016x
- Mode: `history_pack`
- Byte-perfect archive verification: PASS
- `verify-snapshot`: PASS
- Restored file count: 1,547
- `diff -qr` restored directory vs source: PASS

## Strong Baselines

All baselines were built against the same source directory.

| Method | Bytes | Source ratio | Smavg total advantage |
| --- | ---: | ---: | ---: |
| Smavg total store | 334,460 | 511.738x | 1.000x |
| Smavg payload only | 311,184 | 550.016x | 0.930x |
| `tar | xz -9e` | 373,832 | 457.842x | 1.118x |
| `tar | zstd -19 --long=31` | 392,880 | 435.645x | 1.175x |
| `tar | brotli -q 11` | 485,571 | 352.484x | 1.452x |
| Git `.git` file sum after `git gc --aggressive` | 1,103,009 | 155.172x | 3.298x |
| Git pack file only | 871,122 | 196.478x | 2.605x |

## Verification Commands

```bash
PYTHONPATH=src python3 -m smavg.cli --store /tmp/smavg-history-pack-store verify-snapshot --snapshot luau-history-pack
PYTHONPATH=src python3 -m smavg.cli --store /tmp/smavg-history-pack-store restore /tmp/smavg-history-pack-restored --snapshot luau-history-pack
diff -qr /tmp/smavg-archive-v1-luau/corpus/records /tmp/smavg-history-pack-restored
```

The final `diff -qr` returned exit code 0 and no output.

## Interpretation

The compact history-pack mode beats the strongest measured general-purpose
solid-compression baselines on this real versioned-history corpus while keeping
the archive self-describing enough to verify and restore byte-perfect files.

This does not prove Smavg wins on every data type. It proves the current narrow
target: repeated file history with mostly stable bytes and small changes.
