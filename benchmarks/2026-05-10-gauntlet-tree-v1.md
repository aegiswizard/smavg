# Smavg Gauntlet Tree Fidelity v1

Generated on 2026-05-10 with:

```bash
PYTHONPATH=src python3 -m smavg.cli gauntlet --preset all \
  --out /tmp/smavg-gauntlet-2026-05-10-v4 \
  --baselines thorough
```

This gauntlet used real local and public corpora. No synthetic demo corpus was
counted.

## Scope

This run counted full fidelity for:

- regular-file bytes
- relative paths
- directories, including empty directories
- symlinks without following symlink targets
- file and directory permission modes

This run did not claim fidelity for:

- timestamps
- ownership
- hard-link identity

If a corpus had unsupported entries or failed restore/diff/tree checks, it
would not be counted. In this run all 15 corpora were counted.

## Summary

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

The previous blocker was a symlink-containing local corpus. Container v1 now
stores symlink entries as links, does not follow symlink targets, restores the
link target text exactly, and the gauntlet checks that behavior.

## Results

| Corpus | Stage | Files | Dirs | Symlinks | Original | Smavg | Ratio | Best baseline | Smavg vs best | Counted | Tree |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- | --- |
| smavg-repo | local-safe | 41 | 7 | 0 | 338.0 KB | 79.3 KB | 4.264x | brotli 66.7 KB | 0.841x | YES | PASS |
| codex-memories | local-safe | 83 | 4 | 0 | 837.6 KB | 262.4 KB | 3.193x | brotli 192.7 KB | 0.734x | YES | PASS |
| codex-skills | local-safe | 236 | 165 | 0 | 1.1 MB | 450.2 KB | 2.405x | brotli 265.7 KB | 0.590x | YES | PASS |
| kimi-skills | local-safe | 49 | 40 | 0 | 300.6 KB | 148.1 KB | 2.030x | brotli 108.0 KB | 0.729x | YES | PASS |
| smavg-patent-research | local-safe | 8 | 0 | 0 | 79.1 KB | 31.8 KB | 2.486x | brotli 20.5 KB | 0.645x | YES | PASS |
| luau-history-extracted | local-safe | 1547 | 5 | 0 | 163.2 MB | 305.0 KB | 548.104x | xz 365.1 KB | 1.197x | YES | PASS |
| luau-mixed-history | local-safe | 625 | 4 | 0 | 44.7 MB | 173.1 KB | 264.572x | xz 174.1 KB | 1.006x | YES | PASS |
| personal-ops-mcp | local-reality | 3491 | 545 | 1 | 14.4 MB | 2.9 MB | 4.995x | xz 1.6 MB | 0.545x | YES | PASS |
| plugins | local-reality | 72 | 76 | 0 | 201.9 KB | 95.0 KB | 2.125x | brotli 56.1 KB | 0.590x | YES | PASS |
| ontario-dashboard | local-reality | 1 | 0 | 0 | 521.1 KB | 111.5 KB | 4.672x | brotli 79.4 KB | 0.712x | YES | PASS |
| library-diagnostic-reports | local-reality | 23 | 1 | 0 | 164.7 KB | 38.6 KB | 4.264x | brotli 17.7 KB | 0.458x | YES | PASS |
| public-loghub-2k | public | 6 | 0 | 0 | 1.5 MB | 129.8 KB | 11.778x | xz 92.6 KB | 0.713x | YES | PASS |
| public-weather-csv | public | 10 | 0 | 0 | 12.7 MB | 3.4 MB | 3.794x | xz 1.8 MB | 0.530x | YES | PASS |
| public-cisa-kev | public | 1590 | 0 | 0 | 1.2 MB | 177.1 KB | 6.738x | xz 153.9 KB | 0.869x | YES | PASS |
| public-nvd-recent-1000 | public | 1000 | 0 | 0 | 4.6 MB | 380.9 KB | 12.419x | brotli 349.2 KB | 0.917x | YES | PASS |

## Conclusions

The trust result improved materially: the broad gauntlet is now 15/15 counted
with byte-perfect regular-file restore and tree-fidelity restore inside the
declared scope.

The compression result is still intentionally narrow. Smavg beats the strongest
available baseline on versioned-history corpora:

- Luau extracted history: 171,156,036 bytes -> 312,269 bytes, 548.104x.
- Luau mixed history: 46,885,286 bytes -> 177,212 bytes, 264.572x.

The broad public corpora restored correctly and sometimes compressed strongly,
but they did not beat `xz` or `brotli` in this run:

- Loghub: 11.778x Smavg, but `xz` was smaller.
- NVD recent 1000: 12.419x Smavg, but `brotli` was smaller.
- CISA KEV: 6.738x Smavg, but `xz` was smaller.
- Weather CSV: 3.794x Smavg, but `xz` was smaller.

The next compression leap should target public, reproducible families where
Smavg currently restores perfectly but loses to general solid compression:
logs, JSON feeds, and CSV/time-series tables.

## Raw Artifact

The full local JSON and Markdown output was preserved outside the repository at:

```text
/Users/mac/.codex/smavg-private-benchmarks/2026-05-10-gauntlet-tree-v1/
```

