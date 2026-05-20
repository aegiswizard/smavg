# 2026-05-09 Planner v1 Gauntlet

This benchmark validates the first family-aware planner path. It uses real local
files, not mocked data:

- Two real Luau historical file-version directories.
- Five real Smavg project files.
- One real `/bin/ls` system binary.

## Planner-Preserved Luau History

Source:
`/tmp/smavg-archive-v1-luau/corpus/records`

Command:

```bash
PYTHONPATH=src python3 -m smavg.cli --store /tmp/smavg-planner-luau-store archive /tmp/smavg-archive-v1-luau/corpus/records --snapshot-id luau-planner
```

Measured output:

- Files: 1,547
- Original apparent bytes: 171,156,036
- Original disk bytes: 174,338,048
- Smavg store apparent bytes: 337,050
- Smavg store disk bytes: 344,064
- Payload bytes: 311,184
- Apparent ratio: 507.806x
- Disk ratio: 497.454x
- Payload ratio: 550.016x
- Planner families: 1 whole-corpus `history_pack`
- Fallback files: 0
- Archive verify: PASS
- `verify-snapshot`: PASS
- Restore: 1,547 files
- `diff -qr` restored vs source: PASS

Strong baselines from the same source remain:

| Method | Bytes | Source ratio |
| --- | ---: | ---: |
| Smavg Planner v1 total store | 337,050 | 507.806x |
| `tar | xz -9e` | 373,832 | 457.842x |
| `tar | zstd -19 --long=31` | 392,880 | 435.645x |
| `tar | brotli -q 11` | 485,571 | 352.484x |

## Mixed Real Corpus

Source:
`/tmp/smavg-planner-mixed/source`

Corpus composition:

- `history/Analysis_src_ConstraintSolver.cpp`: 323 real historical versions.
- `history/Analysis_src_Frontend.cpp`: 296 real historical versions.
- `unrelated/LICENSE`, `README.md`, `history_pack.py`, `planner.py`,
  `store.py`: real Smavg project files.
- `unrelated/ls-binary`: real `/bin/ls` system binary.

Command:

```bash
PYTHONPATH=src python3 -m smavg.cli --store /tmp/smavg-planner-mixed-store archive /tmp/smavg-planner-mixed/source --snapshot-id mixed-real-planner
```

Measured output:

- Files: 625
- Original apparent bytes: 46,885,286
- Original disk bytes: 48,222,208
- Smavg store apparent bytes: 216,975
- Smavg store disk bytes: 225,280
- Payload bytes: 175,332
- Apparent ratio: 216.086x
- Disk ratio: 208.120x
- Payload ratio: 267.409x
- Planner families: 2 `history_pack` families, 619 files.
- Fallback: 6 files in safe per-file object storage.
- Archive verify: PASS
- `verify-snapshot`: PASS
- Restore: 625 files
- `diff -qr` restored vs source: PASS

Planner report:

```text
Families detected: 2
  history_pack parent:history/Analysis_src_ConstraintSolver.cpp: 323 files, 82564 payload bytes, 376.525x payload
  history_pack parent:history/Analysis_src_Frontend.cpp: 296 files, 40564 payload bytes, 383.49x payload
Fallback: 6 files, safe_object_store
```

Mixed-corpus baselines:

| Method | Bytes | Source ratio | Notes |
| --- | ---: | ---: | --- |
| Smavg total store | 216,975 | 216.086x | Includes SQLite + manifest overhead |
| Smavg payload only | 175,332 | 267.409x | Beats measured solid-compression payloads |
| `tar | xz -9e` | 178,308 | 262.945x | Smaller than total Smavg store on this smaller mixed corpus |
| `tar | zstd -19 --long=31` | 187,012 | 250.707x | Smaller than total Smavg store |
| `tar | brotli -q 11` | 193,676 | 242.081x | Smaller than total Smavg store |

## Interpretation

Planner v1 proves the next architecture step:

- It can detect real versioned-history families inside a mixed folder.
- It can store unrelated files separately instead of forcing everything through
  one history chain.
- It keeps byte-perfect restore across packs and fallback files.
- It now produces a report explaining what was detected and what fell back.

The mixed corpus also exposes the next engineering target: on smaller archives,
metadata overhead can erase a payload win. The next format work should compact
snapshot metadata or add a single-file archive container before claiming broad
mixed-corpus wins over `xz`.
