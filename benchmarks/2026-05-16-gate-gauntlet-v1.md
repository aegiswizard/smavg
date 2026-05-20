# Smavg Strict Gate Gauntlet v1

Date: 2026-05-16

This pass tests Smavg as an input gate, not only as a compressor. The gauntlet
uses raw local files only as the scoring oracle. A counted Smavg path must use
the generated gate packet first and must supply exact task evidence through
receipt-aware `expand-context` calls.

## What Was Tested

For each real local Codex/Smavg work surface, the gauntlet checks:

- Gate packet exists and records that Smavg did not supply the full raw source.
- Receipt exists and records the same raw-source boundary.
- Every required file expands exactly through `smavg expand-context --receipt`.
- Every required path is visible in the context markdown so a receiving model
  has a route to the exact file.
- Evidence terms from exact expanded files match the raw local oracle.
- The receipt-token path is smaller than raw source tokens.

This is not a live-model reasoning benchmark. It is a stricter evidence harness
that proves the Smavg gate path did not remove the facts needed for the tested
tasks.

## Code Changes

- Added `src/smavg/gate_gauntlet.py`.
- Added CLI command `smavg gate-gauntlet`.
- Added `tests/test_gate_gauntlet.py`.
- Updated README and the Smavg local skill with the strict gate-gauntlet flow.

## Command

```bash
cd /Users/mac/smavg
PYTHONPATH=src python3 -m smavg.cli gate-gauntlet \
  --out /Users/mac/.codex/smavg-private-benchmarks/2026-05-16-gate-gauntlet-v1 \
  --reset \
  --budget 3000 \
  --repeat-count 3
```

Raw local artifacts:

`/Users/mac/.codex/smavg-private-benchmarks/2026-05-16-gate-gauntlet-v1/`

## Summary

| Metric | Result |
| --- | ---: |
| Probes | 7 |
| PASS | 7/7 |
| Gate integrity PASS | 7/7 |
| Receipt integrity PASS | 7/7 |
| Exact expansion PASS | 7/7 |
| Model routing PASS | 7/7 |
| Evidence tasks PASS | 16/16 |
| Same evidence | 16/16 |
| Raw tokens estimate | 3,314,432 |
| Gate receipt tokens estimate | 140,736 |
| Receipt reduction | 23.551x |
| Three-task raw tokens estimate | 9,943,296 |
| Three-task gate tokens estimate | 140,736 |
| Repeated-work reduction | 70.652x |
| Full raw source supplied by Smavg | false |

## Per-Probe Results

| Probe | Status | Raw tokens | Receipt tokens | Receipt reduction | Repeated-work reduction | Evidence tasks |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| smavg-dev | PASS | 160,113 | 40,279 | 3.975x | 11.925x | 3/3 |
| codex-memories | PASS | 217,281 | 33,536 | 6.479x | 19.437x | 2/2 |
| codex-skills | PASS | 238,976 | 10,480 | 22.803x | 68.409x | 2/2 |
| agents-skills | PASS | 129,469 | 3,247 | 39.873x | 119.620x | 2/2 |
| codex-plugin-cache | PASS | 2,509,441 | 43,415 | 57.801x | 173.404x | 3/3 |
| workflow-x-browsermcp | PASS | 29,372 | 4,991 | 5.885x | 17.655x | 2/2 |
| workflow-hackernews-browsermcp | PASS | 29,780 | 4,788 | 6.220x | 18.659x | 2/2 |

## Interpretation

This is the strictest current proof for using Smavg as the setup front door for
agent work:

- Smavg did not supply the full raw source in any counted probe.
- Every counted task got its evidence through exact, hash-verified expansion.
- The receipt recorded every exact expansion.
- Raw-source evidence and gated exact-file evidence matched for all 16 tasks.
- The token reduction remains meaningful after paying the cost of exact file
  expansion and receipt accounting.

The honest boundary:

- This does not prove an arbitrary model will always reason perfectly from the
  gate packet.
- It proves the gate packet plus exact expansions preserve the tested evidence
  while supplying much less context than raw full-source reading.
- This current Codex chat already contains historical raw context, so this
  report should be used as the reproducible clean-path measurement.

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m compileall src/smavg tests
PYTHONPATH=src python3 -m smavg.cli gate-gauntlet --help
```

Result:

- Full test suite passed: 68 tests.
- Compile check passed.
- `smavg gate-gauntlet` CLI help rendered successfully.
