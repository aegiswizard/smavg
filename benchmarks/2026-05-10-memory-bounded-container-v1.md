# Smavg Memory-Bounded Container v1.1

Generated on 2026-05-10 after the Container v1.1 memory pass.

## What Changed

Container read/write paths were changed without changing the `.smavg` file
layout:

- `read_container` reads the fixed header and compressed manifest, not the full
  archive.
- Payload-region SHA-256 verification streams the payload region in chunks.
- Payload records are read by offset and length.
- `full_zlib` fallback records verify and restore as streams.
- `pack_container` spools payload bytes to a temporary payload file instead of
  building `payload_parts` and joining them in RAM.
- Restore writes fallback bytes to temporary files and atomically moves them
  into place after size and SHA-256 checks pass.

Current honest exception: `history_pack_v2_lzma` is still decoded as a whole
active family segment. The container no longer requires archive-sized RAM, but
large history families still require checkpointed history packs before memory is
bounded by chunk instead of family.

## Verification

Unit and bytecode checks:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m compileall -q src tests
```

Result:

- 44 tests passed.
- `compileall` passed.

Full real gauntlet:

```bash
PYTHONPATH=src python3 -m smavg.cli gauntlet --preset all \
  --out /tmp/smavg-gauntlet-2026-05-10-memory-v1 \
  --baselines thorough
```

Result:

| Metric | Result |
| --- | ---: |
| Corpora | 15 |
| Counted | 15 |
| Not counted | 0 |
| Verify PASS | 15 |
| Restore PASS | 15 |
| Regular-file byte diff PASS | 15 |
| Tree fidelity PASS | 15 |
| Counted corpora beating best available baseline | 2 |

## Key Compression Rows

| Corpus | Original | Smavg | Ratio | Best baseline | Smavg vs best |
| --- | ---: | ---: | ---: | ---: | ---: |
| Luau extracted history | 171,156,036 | 312,269 | 548.104x | `xz` 373,832 | 1.197x |
| Luau mixed history | 46,885,286 | 177,213 | 264.570x | `xz` 178,308 | 1.006x |
| Public Loghub 2k | 1,565,627 | 132,931 | 11.778x | `xz` 94,656 | 0.712x |
| Public weather CSV | 13,350,865 | 3,519,240 | 3.794x | `xz` 1,861,636 | 0.529x |
| Public CISA KEV | 1,222,112 | 181,382 | 6.738x | `xz` 157,252 | 0.867x |
| Public NVD recent 1000 | 4,562,727 | 337,301 | 13.527x | `brotli` 307,556 | 0.912x |

The trust result stayed intact. Compression leadership remains narrow:
versioned-history corpora beat the strongest measured baselines; public logs,
JSON, and CSV restore perfectly but still lose to `xz`/`brotli`.

## Peak Memory Measurements

Measured with `/usr/bin/time -l` on macOS. Values below are `maximum resident
set size`, so they include Python interpreter overhead.

| Operation | Real target | Archive/source size | Max RSS |
| --- | --- | ---: | ---: |
| Pack | Luau mixed source | 46,885,286 source bytes | 172,343,296 bytes |
| Verify | Luau extracted history archive | 312,269 archive bytes | 223,358,976 bytes |
| Restore | Luau extracted history archive | 312,269 archive bytes | 212,623,360 bytes |
| Verify | Public weather CSV archive | 3,519,240 archive bytes | 24,678,400 bytes |
| Restore | Public weather CSV archive | 3,519,240 archive bytes | 31,956,992 bytes |

Interpretation:

- Fallback-heavy archives now verify and restore with low memory relative to
  archive/source size.
- History-pack archives still use high memory because the current history-pack
  codec reconstructs a whole family in memory.
- The next memory milestone is checkpointed/chunked history packs, not another
  container layout change.

## Raw Artifact

The full local gauntlet JSON and Markdown output was preserved outside the
repository at:

```text
/Users/mac/.codex/smavg-private-benchmarks/2026-05-10-memory-v1/
```

