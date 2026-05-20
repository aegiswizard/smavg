# Smavg Codex A/B Evidence Gauntlet v1

Date: 2026-05-16

This pass adds task-level A/B scoring to the Codex workload gauntlet.

The goal is not to pretend that a deterministic script is an AI model. The goal
is stricter and more useful for trust: prove that the Smavg path gives Codex the
same required task evidence as raw full-context reading, while using fewer
tokens and only expanding exact hash-verified files.

## What Was Tested

For each task, the gauntlet compares:

- Raw path: full local workload surface is available.
- Smavg path: compact context brief first, then exact required file expansions.
- Correctness: required evidence terms must be present in both paths.
- Same evidence: raw and Smavg term hits must match.
- Routing: required exact paths must be visible in the compact brief.

This is an evidence A/B test, not an AI-generated answer benchmark.

## Code Changes

- Extended `src/smavg/codex_gauntlet.py` with deterministic A/B evidence
  tasks.
- Added `CodexEvidenceTask` definitions for real local Codex surfaces.
- Updated CLI summary output for `smavg codex-gauntlet` to include A/B task
  pass counts and A/B token reduction.
- Updated tests in `tests/test_codex_gauntlet.py`.

## Command

```bash
cd /Users/mac/smavg
PYTHONPATH=src python3 -m smavg.cli codex-gauntlet \
  --out /Users/mac/.codex/smavg-private-benchmarks/2026-05-16-codex-ab-gauntlet-v1-stable \
  --reset \
  --budget 3000 \
  --repeat-count 3
```

Raw local artifacts:

`/Users/mac/.codex/smavg-private-benchmarks/2026-05-16-codex-ab-gauntlet-v1-stable/`

## Summary

| Metric | Result |
| --- | ---: |
| Probes | 7 |
| Exact expansion pass | 7/7 |
| Model-routing pass | 7/7 |
| First-time useful | 7/7 |
| Repeated useful | 7/7 |
| A/B evidence tasks | 16/16 PASS |
| A/B raw correct | 16/16 |
| A/B Smavg correct | 16/16 |
| A/B same evidence | 16/16 |
| Total raw tokens estimate | 3,286,261 |
| Total brief tokens estimate | 27,259 |
| Brief-only reduction | 120.557x |
| First-time Smavg tokens estimate | 131,871 |
| First-time reduction | 24.920x |
| Three-task raw tokens estimate | 9,858,783 |
| Three-task Smavg tokens estimate | 131,871 |
| Repeated-work reduction | 74.761x |
| A/B raw task tokens estimate | 9,219,172 |
| A/B Smavg task tokens estimate | 139,495 |
| A/B token reduction | 66.090x |

## Per-Surface A/B Results

| Probe | A/B tasks | A/B reduction |
| --- | ---: | ---: |
| Smavg repo development | 3/3 PASS | 19.676x |
| Codex memories | 2/2 PASS | 17.961x |
| Codex skills | 2/2 PASS | 33.112x |
| `.agents` skills | 2/2 PASS | 62.819x |
| Codex plugin cache | 3/3 PASS | 118.551x |
| X BrowserMCP workflow | 2/2 PASS | 8.913x |
| Hacker News BrowserMCP workflow | 2/2 PASS | 9.054x |

## Interpretation

This is the first Smavg result that tests correctness at the task-evidence
level.

The important result is:

- raw full-context evidence and Smavg exact-expanded evidence matched on all
  16 tasks
- every required file expanded through SHA-256 verified exact retrieval
- every required path was visible in the compact brief
- Smavg kept large token reductions even after adding enough file-index context
  for model routing

The honest boundary remains:

- This does not prove an arbitrary AI model will always reason perfectly.
- It proves Smavg did not remove the required task evidence for these real
  local Codex workloads.
- A future live-model A/B can now use this gauntlet as the evidence harness:
  ask the model to answer from raw context, ask again from Smavg context plus
  exact expansions, then grade against the same evidence terms.

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
