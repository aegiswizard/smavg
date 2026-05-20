# Smavg History Pack v4 Report

Generated on 2026-05-11.

## What Changed

History Pack v4 is a focused compression and trust improvement for versioned
text/code history.

- New codec: `history_pack_v4_merkle_lzma`.
- V4 keeps the chunked history-pack container shape from v3.
- V4 removes repeated per-member path, size, and SHA-256 metadata from the
  compressed delta stream.
- V4 stores member paths and groups in the compact zlib index and stores a
  SHA-256 chunk root over restored `(path, size, sha256(bytes))` records.
- V4 decode verifies the compressed chunk hash, reconstructed logical size,
  file count, and chunk root before accepting the chunk.
- The encoder self-check now streams through the produced history pack instead
  of decoding the whole restored corpus into a dict.
- Default history checkpoint interval is now 2048.

This keeps the project rule intact: every accepted archive must restore
byte-perfect, and the codec is selected only after real self-verification.

## Verification

```text
PYTHONPATH=src python3 -m unittest discover -s tests
Ran 47 tests: OK

PYTHONPATH=src python3 -m compileall -q src tests
PASS
```

Focused real Luau history check:

```text
rm -rf /tmp/smavg-v4-luau.smavg /tmp/smavg-v4-luau-restored
/usr/bin/time -l env PYTHONPATH=src python3 -m smavg.cli pack \
  /tmp/smavg-archive-v1-luau/corpus/records \
  --out /tmp/smavg-v4-luau.smavg
PYTHONPATH=src python3 -m smavg.cli report /tmp/smavg-v4-luau.smavg
PYTHONPATH=src python3 -m smavg.cli verify /tmp/smavg-v4-luau.smavg
/usr/bin/time -l env PYTHONPATH=src python3 -m smavg.cli restore \
  /tmp/smavg-v4-luau.smavg \
  /tmp/smavg-v4-luau-restored
diff -qr /tmp/smavg-archive-v1-luau/corpus/records /tmp/smavg-v4-luau-restored
```

Focused real mixed-corpus check:

```text
rm -rf /tmp/smavg-v4-mixed.smavg /tmp/smavg-v4-mixed-restored
PYTHONPATH=src python3 -m smavg.cli pack \
  /tmp/smavg-planner-mixed/source \
  --out /tmp/smavg-v4-mixed.smavg
PYTHONPATH=src python3 -m smavg.cli report /tmp/smavg-v4-mixed.smavg
PYTHONPATH=src python3 -m smavg.cli verify /tmp/smavg-v4-mixed.smavg
PYTHONPATH=src python3 -m smavg.cli restore \
  /tmp/smavg-v4-mixed.smavg \
  /tmp/smavg-v4-mixed-restored
diff -qr /tmp/smavg-planner-mixed/source /tmp/smavg-v4-mixed-restored
```

## Key Results

| Corpus | Original | Smavg v4 | Ratio | Best baseline | Smavg vs best | Codec decision |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Luau history extracted | 171,156,036 | 277,293 | 617.239x | xz 373,832 | 1.348x | v4 chunk-root history |
| Luau mixed history | 46,885,286 | 164,556 | 284.920x | xz 178,308 | 1.084x | v4 for 2 history families, full_zlib fallback for 6 files |

## Luau History Details

```text
Archive: /tmp/smavg-v4-luau.smavg
Files: 1547
Logical bytes: 171156036
Archive bytes: 277293
Ratio: 617.239
Payload ratio: 619.679
Family detection:
  history_pack whole-corpus-history: 1547 files, 276201 payload bytes,
  history_pack_v4_merkle_lzma
Fallback files: 0
Integrity: PASS
Overhead:
  payload: 276201 bytes
  manifest: 1004 bytes
  header: 88 bytes
```

Strong baseline comparison on the same corpus:

| Method | Bytes | Source ratio |
| --- | ---: | ---: |
| Smavg v4 `.smavg` | 277,293 | 617.24x |
| `tar | xz -9e` | 373,832 | 457.84x |
| `tar | zstd -19 --long=31` | 392,880 | 435.65x |
| `tar | brotli -q 11` | 485,571 | 352.48x |
| Git `.git` file sum after `git gc --aggressive` | 1,103,009 | 155.17x |

Previous Smavg comparison on the same Luau corpus:

| Version | Bytes | Ratio |
| --- | ---: | ---: |
| Monolithic history payload/container before v3 | 312,269 | 548.104x |
| History Pack v3 chunked container | 337,666 | 506.880x |
| History Pack v4 chunk-root container | 277,293 | 617.239x |

V4 is 1.218x smaller than v3 on this corpus and 1.126x smaller than the
previous compact monolithic history result, while preserving chunked restore and
single-file extraction.

## Mixed Corpus Details

```text
Archive: /tmp/smavg-v4-mixed.smavg
Files: 625
Logical bytes: 46885286
Archive bytes: 164556
Ratio: 284.920
Payload ratio: 288.223
Family detection:
  history_pack parent:history/Analysis_src_ConstraintSolver.cpp:
    323 files, 75506 payload bytes, history_pack_v4_merkle_lzma
  history_pack parent:history/Analysis_src_Frontend.cpp:
    296 files, 34960 payload bytes, history_pack_v4_merkle_lzma
Fallback files: 6
Integrity: PASS
Overhead:
  payload: 162670 bytes
  manifest: 1798 bytes
  header: 88 bytes
```

Strong baseline comparison on the same corpus:

| Method | Bytes | Source ratio |
| --- | ---: | ---: |
| Smavg v4 `.smavg` | 164,556 | 284.92x |
| `tar | xz -9e` | 178,308 | 262.95x |
| `tar | zstd -19 --long=31` | 187,012 | 250.71x |
| `tar | brotli -q 11` | 193,676 | 242.08x |

V4 is 1.077x smaller than the previous Smavg mixed result of 177,209 bytes and
1.084x smaller than the best measured general baseline.

## Memory And Random Access

Measured on the v4 Luau history archive:

```text
pack:    PASS, 139.74s, 318,787,584 bytes max RSS
verify:  PASS,   1.11s,  40,570,880 bytes max RSS
restore: PASS,   1.54s,  39,989,248 bytes max RSS
extract: PASS,   1.09s,  42,844,160 bytes max RSS
```

The extracted real file was:

```text
Analysis_src_ConstraintSolver.cpp/0304-217d7546548b
```

It restored as 140,434 bytes and matched the source with `cmp`.

The pack path is still the expensive path because LZMA extreme dominates CPU
and memory. The v4 streaming self-check removed one major memory problem: it no
longer holds the whole restored corpus in a Python dict during encode. After
that change, pack max RSS dropped from 405,442,560 bytes to 318,787,584 bytes
on the same corpus.

## Honest Ceiling

This is not the 1000x result. On this exact Luau corpus, inserted changed text
already compresses to roughly the same scale as the final target for 1000x, so
getting there would require a deeper code-aware model, not another small
metadata cleanup.

What v4 proves is still substantial:

- The versioned-history category moved from 548x to 617x.
- The chunked bounded-reader path is now smaller than the older compact
  monolithic result.
- The mixed corpus widened its lead over `xz`.
- Byte-perfect restore, verify, full diff, and single-file extraction all pass
  on real local data.

