# Smavg Codex Workload Gauntlet v1

Date: 2026-05-16

This pass tests whether Smavg helps Codex work correctly, not only whether it
compresses local files.

The gauntlet measures:

- raw tokens if Codex reads the whole workload surface
- Smavg context-brief tokens
- Smavg brief plus exact required file expansions for a first-time task
- repeated-work setup tokens for three repeated tasks
- exact expansion and SHA-256 verification
- whether the markdown brief exposes the files the model must choose

## Code Changes

- Added `src/smavg/codex_gauntlet.py`.
- Added CLI command:
  `smavg codex-gauntlet`.
- Added compact exact-file index output to `smavg context` briefs.
- Added tests:
  `tests/test_codex_gauntlet.py`.

The compact exact-file index is important. Before this pass, exact expansion
worked everywhere, but some required files were not visible in the markdown
brief. That meant a model reading only the brief might need an exact path or a
query/list step. After adding the compact index, the same real gauntlet reached
7/7 model-routing pass.

## Command

```bash
cd /Users/mac/smavg
PYTHONPATH=src python3 -m smavg.cli codex-gauntlet \
  --out /Users/mac/.codex/smavg-private-benchmarks/2026-05-16-codex-workload-gauntlet-v1-indexed \
  --reset \
  --budget 3000 \
  --repeat-count 3
```

Raw local artifacts:

`/Users/mac/.codex/smavg-private-benchmarks/2026-05-16-codex-workload-gauntlet-v1-indexed/`

## Summary

| Metric | Result |
| --- | ---: |
| Probes | 7 |
| Exact expansion pass | 7/7 |
| Model-routing pass | 7/7 |
| First-time useful | 7/7 |
| Repeated useful | 7/7 |
| Total raw tokens estimate | 3,276,329 |
| Total brief tokens estimate | 27,194 |
| Brief-only reduction | 120.480x |
| First-time Smavg tokens estimate | 129,352 |
| First-time reduction | 25.329x |
| Three-task raw tokens estimate | 9,828,987 |
| Three-task Smavg tokens estimate | 129,352 |
| Repeated-work reduction | 75.986x |

## Per-Surface Results

| Probe | Exact | Routing | Raw tokens | Brief tokens | First-time reduction | Repeated reduction |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| Smavg repo development | PASS | PASS | 131,094 | 3,452 | 3.916x | 11.747x |
| Codex memories | PASS | PASS | 213,562 | 3,782 | 7.163x | 21.488x |
| Codex skills | PASS | PASS | 238,111 | 5,744 | 24.765x | 74.294x |
| `.agents` skills | PASS | PASS | 129,469 | 875 | 39.873x | 119.620x |
| Codex plugin cache | PASS | PASS | 2,509,441 | 10,560 | 57.801x | 173.404x |
| X BrowserMCP workflow | PASS | PASS | 27,122 | 1,293 | 5.434x | 16.303x |
| Hacker News BrowserMCP workflow | PASS | PASS | 27,530 | 1,488 | 5.750x | 17.249x |

## Interpretation

This is stronger than a compression-only result.

The important finding is that Smavg can act as a Codex operating memory layer
across local skills, memories, plugin caches, workflows, and the Smavg repo
itself:

- one-off guided tasks still saved tokens when only a few exact files were
  needed
- repeated workflows saved much more
- exact required files expanded cleanly in every probe
- the compact brief exposed every required file path after the file-index pass

The honest boundary remains:

- Smavg cannot reduce brand-new live browser/page content.
- If a task truly requires every file's full contents, Smavg should report weak
  or modest savings.
- Token counts are deterministic estimates over local files, not a private
  Codex account billing meter.
- Work quality must keep being tested through exact expansion and model-routing
  checks, not inferred from compression ratio alone.

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m compileall -q src tests
python3 /Users/mac/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  /Users/mac/.codex/skills/smavg-repetition-firewall
```

Result:

- Full test suite passed: 62 tests.
- Compile check passed.
- Smavg skill is valid.

