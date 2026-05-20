# Smavg History Pack v3 Report

Generated on 2026-05-10.

## What Changed

History packs now have an adaptive codec choice:

- Large history families use `history_pack_v3_chunked_lzma`.
- V3 stores a compact zlib index plus independently compressed LZMA checkpoint
  chunks.
- V3 supports bounded-memory verify/restore and single-file extraction from the
  target chunk.
- Smaller history families may still use `history_pack_v2_lzma` when the
  planner measures v2 as smaller than v3.
- The container report now exposes the selected history codec.
- New command: `smavg extract archive.smavg path/in/archive --out file`.

This keeps the trust rule intact: every archive is still verified byte-perfect
before it is accepted.

## Verification

```text
PYTHONPATH=src python3 -m unittest discover -s tests
Ran 46 tests: OK

PYTHONPATH=src python3 -m compileall -q src tests
PASS
```

Full real gauntlet:

```text
PYTHONPATH=src python3 -m smavg.cli gauntlet --preset all \
  --out /tmp/smavg-gauntlet-2026-05-10-history-v3 \
  --baselines thorough
```

Summary:

```text
Corpora: 15
Counted: 15
Full-fidelity counted: 15
Verify PASS: 15
Restore PASS: 15
Regular-file diff PASS: 15
Tree fidelity PASS: 15
Counted corpora beating best available baseline: 2
```

Raw local artifacts:

```text
/Users/mac/.codex/smavg-private-benchmarks/2026-05-10-history-v3/report.md
/Users/mac/.codex/smavg-private-benchmarks/2026-05-10-history-v3/results.json
```

## Key Results

| Corpus | Original | Smavg | Ratio | Best baseline | Smavg vs best | Codec decision |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Luau history extracted | 171,156,036 | 337,666 | 506.880x | xz 373,832 | 1.107x | v3 chunked |
| Luau mixed history | 46,885,286 | 177,209 | 264.576x | xz 178,308 | 1.006x | v2 for small families |
| Public Loghub 2k | 1,565,627 | 132,931 | 11.778x | xz 94,884 | 0.714x | fallback/family mix |
| Public weather CSV | 13,350,865 | 3,519,241 | 3.794x | xz 1,862,096 | 0.529x | fallback/family mix |
| Public CISA KEV | 1,222,112 | 198,864 | 6.145x | xz 157,300 | 0.791x | fallback/family mix |
| Public NVD recent 1000 | 4,562,727 | 337,297 | 13.527x | brotli 307,830 | 0.913x | fallback/family mix |

## Memory And Random Access

Measured on the v3 Luau history archive:

```text
verify:  PASS, 1.06s, 38,404,096 bytes max RSS
restore: PASS, 1.55s, 34,983,936 bytes max RSS
extract: PASS, 0.32s, 31,227,904 bytes max RSS
```

The extracted real file was:

```text
Analysis_src_ConstraintSolver.cpp/0304-217d7546548b
```

It restored as 140,434 bytes and matched the source with `cmp`.

## Honest Tradeoff

The previous monolithic history payload reached about 548x on the Luau history
corpus. V3 deliberately gives up some compression there, landing at 506.88x, to
gain bounded-memory restore and random extraction while still beating the best
general baseline. The mixed corpus keeps its narrow `xz` win because the
planner chooses v2 for smaller history families where v3 metadata overhead
would be counterproductive.

This is the correct current behavior: Smavg picks the smallest verified safe
plan, not the newest codec for its own sake.
