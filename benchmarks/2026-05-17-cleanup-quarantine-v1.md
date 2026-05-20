# Smavg Cleanup Quarantine Projection v1

Date: 2026-05-17

This pass extends `smavg safe-pack` with cleanup economics and an importance
briefing. The command still does not delete anything. It reports what happened
now and what would happen only if the quarantined original were later purged.

## What Was Tested

Real local source:

`/tmp/smavg-gate-smoke`

This was a prior real Smavg gate artifact folder created from the Smavg repo,
not a synthetic demo folder. The test was safe because it moved only this
temporary artifact, not the live repository or durable memory.

## Command

```bash
cd /Users/mac/smavg
PYTHONPATH=src python3 -m smavg.cli safe-pack /tmp/smavg-gate-smoke \
  --out /Users/mac/.codex/smavg-private-benchmarks/2026-05-16-cleanup-quarantine-v1/smavg-gate-smoke.smavg \
  --work-dir /Users/mac/.codex/smavg-private-benchmarks/2026-05-16-cleanup-quarantine-v1/work \
  --report /Users/mac/.codex/smavg-private-benchmarks/2026-05-16-cleanup-quarantine-v1/report.json \
  --quarantine-dir /Users/mac/.codex/smavg-private-benchmarks/2026-05-16-cleanup-quarantine-v1/quarantine \
  --move-to-quarantine
```

Raw local artifacts:

`/Users/mac/.codex/smavg-private-benchmarks/2026-05-16-cleanup-quarantine-v1/`

## Summary

| Metric | Result |
| --- | ---: |
| Archive verify | PASS |
| Restore compare | PASS |
| Delete performed | false |
| Source moved to quarantine | true |
| Files | 8 |
| Source apparent bytes | 157,637 |
| Source disk bytes | 176,128 |
| Archive apparent bytes | 16,278 |
| Archive disk bytes | 16,384 |
| Archive storage ratio | 9.684x |
| Disk freed now | 0 bytes |
| Disk freed if quarantine purged | 176,128 bytes |
| Net disk saved after purge while keeping archive | 159,744 bytes |
| Net disk reduction after purge | 10.750x |
| Raw source tokens estimate | 38,229 |
| Smavg brief tokens estimate | 1,639 |
| Token reduction if agent uses Smavg brief | 23.325x |
| Tokens saved from normal agent setup | 36,590 |
| Importance rating | medium |
| Purge risk | medium |

## Truth Boundary

- Quarantine movement cleaned the active `/tmp/smavg-gate-smoke` path.
- Quarantine movement freed `0` bytes immediately because the quarantined copy
  still exists on disk.
- Real disk recovery would happen only if the quarantine folder were later
  purged or moved off this disk.
- Token reduction is not caused by deletion. Token reduction comes from using
  the Smavg brief/gate instead of sending the raw source files to an agent.
- Exact restore remains backed by the `.smavg` archive and the successful
  restore comparison.

## Importance Brief

Smavg rated this folder `medium` importance / `medium` purge risk because it
contained benchmark/report/receipt/context evidence artifacts:

- `smavg-repo-gate/context.json`
- `smavg-repo-gate/context.md`
- `smavg-repo-gate/preflight.json`
- `smavg-repo-gate/preflight.md`
- `smavg-repo-gate/receipt.json`
- `smavg-repo-gate/receipt.md`

This rating is advisory. It is generated from deterministic local path/content
signals and does not authorize deletion.

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_safe_scan_receipt -v
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m compileall src/smavg tests
```

Result:

- Focused safe scan/receipt tests passed: 3 tests.
- Full suite passed: 68 tests.
- Compile check passed.
