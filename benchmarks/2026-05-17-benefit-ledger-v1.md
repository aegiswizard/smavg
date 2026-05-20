# Smavg Benefit Ledger and Session Counter v1.1

Date: 2026-05-17

This pass upgrades the durable Smavg Benefit Ledger from a small seeded report
into the local all-time scoreboard for Smavg work on this Mac.

The goal is still not to claim provider billing-meter access. The goal is to
record Smavg-visible benefits with the same X-denomination everywhere:

```text
Before -> After -> Saved -> Reduction X -> Truth boundary
```

## What Was Built

- `src/smavg/ledger.py`: append-only benefit event schema, report importers,
  bulk report-folder import, headline counters, lifetime aggregation,
  task/session counter, and markdown rendering.
- CLI:
  - `smavg ledger add`
  - `smavg ledger add-report`
  - `smavg ledger import-reports`
  - `smavg ledger report`
  - `smavg ledger list`
  - `smavg task start`
  - `smavg task add`
  - `smavg task add-report`
  - `smavg task report`
  - `smavg task end`
- Tests:
  - `tests/test_ledger_task.py`

## Import Rule

`smavg ledger import-reports ROOT` recursively scans JSON reports, imports
supported Smavg reports, and suppresses lower-level component JSON when a
top-level report already summarizes the same run.

That means a gauntlet `results.json` can count, while nested `context.json`
files from that same gauntlet are not counted again.

Supported imports now include:

- `smavg-gate-gauntlet`
- `smavg-codex-workload-gauntlet`
- `smavg-safe-pack-report`
- `smavg-run-receipt`
- `smavg-preflight`
- `smavg-context`
- `smavg-gauntlet-v1`
- `smavg-gate`
- workflow token-use summary JSON

## Local Ledger

Default local ledger:

`/Users/mac/.smavg/ledger/events.jsonl`

Lifetime markdown:

`/Users/mac/.smavg/ledger/lifetime.md`

The local ledger was rebuilt from the real report folders:

```bash
cd /Users/mac/smavg
PYTHONPATH=src python3 -m smavg.cli ledger import-reports \
  /Users/mac/.codex/smavg-private-benchmarks
PYTHONPATH=src python3 -m smavg.cli ledger import-reports \
  /Users/mac/.codex/smavg-preflights
PYTHONPATH=src python3 -m smavg.cli ledger report \
  --period all \
  --out /Users/mac/.smavg/ledger/lifetime.md
```

Import result:

| Root | JSON scanned | Selected reports | Suppressed components | Imported | Failures |
| --- | ---: | ---: | ---: | ---: | ---: |
| `.codex/smavg-private-benchmarks` | 101 | 32 | 68 | 32 | 0 |
| `.codex/smavg-preflights` | 13 | 6 | 7 | 6 | 0 |

## Headline Counters

These are the simple ordinary-user counters.

| Counter | Current value |
| --- | ---: |
| Tokens saved today | 180,909 |
| Tokens saved all time | 27,309,567 |
| Repeated-work tokens saved today | 0 |
| Repeated-work tokens saved all time | 58,456,133 |
| Disk saved today | 0 bytes |
| Disk saved all time | 1,062,591,198 bytes |

The today counter moved after the first real Smavg Work Mode task. Importing
old evidence does not count as new savings today; ending real work does.

## Lifetime Result

| Metric | Before | After | Saved | Reduction |
| --- | ---: | ---: | ---: | ---: |
| AI/context tokens | 28,155,063 | 845,829 | 27,309,234 | 33.287x |
| Repeated-work tokens | 59,239,323 | 783,190 | 58,456,133 | 75.639x |
| Storage disk bytes | 1,094,676,480 | 32,085,282 | 1,062,591,198 | 34.118x |

The headline token-saved counter is slightly higher than the net AI/context
saved row because per-event headline savings do not subtract weak cases where
Smavg honestly reported no text benefit.

## Per-Category Cards

The ledger keeps category cards separate from lifetime totals so no single
roll-up hides where Smavg is strong, useful, weak, or not applicable.

| Category | Events | Main reduction | Trust |
| --- | ---: | --- | --- |
| Storage | 4 | 1,094,500,352 disk bytes -> 32,068,898, 34.130x | restore 59/60, verify 59/60 |
| Cleanup / Quarantine | 1 | 176,128 disk bytes -> 16,384, 10.750x; 38,229 tokens -> 1,639, 23.325x | restore 1/1, verify 1/1 |
| AI Context | 26 | 8,129,950 tokens -> 49,504, 164.228x | exact expansion 1/1; weak cases 3 |
| Agent Workflow | 7 | 19,794,479 tokens -> 783,190, 25.274x; repeated 59,239,323 -> 783,190, 75.639x | exact expansion 44/44, evidence tasks 64/64 |
| Task Session Counter | 1 | 192,405 tokens -> 11,496, 16.737x | exact expansion 1/1 |
| MCP / Skill / Plugin Usage | 1 | 72,057 tokens -> 4,554, 15.823x | exact expansion 2/2 |
| Weak / No-Benefit Cases | 3 | reported separately, never counted as failures or hidden | failures counted as wins 0 |

Standing reporting rule:

```text
Never hide categories inside one number.
Show each X where it belongs.
Then show lifetime totals as a roll-up.
```

Trust totals:

| Metric | Result |
| --- | ---: |
| Events | 39 |
| Exact expansion | 46/46 |
| Evidence tasks | 64/64 |
| Restore | 60/61 |
| Verify | 60/61 |
| Quarantine moves | 1 |
| Deletes performed by Smavg | 0 |
| Weak cases reported | 3 |
| Failures counted as wins | 0 |

## Task Session Smoke

The task/session counter remains the visible in/out counter for future work:

```bash
PYTHONPATH=src python3 -m smavg.cli task start "Task label"
PYTHONPATH=src python3 -m smavg.cli task add --role user --text "User prompt"
PYTHONPATH=src python3 -m smavg.cli task add --role assistant --text "Assistant output"
PYTHONPATH=src python3 -m smavg.cli task add-report path/to/report.json
PYTHONPATH=src python3 -m smavg.cli task end --out task-report.md
```

Boundary: visible task counters are user-recorded estimates. They do not claim
private Codex/provider accounting.

## Truth Boundary

Standing wording for ledger/session reports:

```text
Smavg-visible estimate, not provider billing meter. Hidden system, developer,
tool-schema, retained-history, and provider-side accounting tokens are not
visible to Smavg unless the host exposes them.
```

This means the ledger can prove what Smavg intentionally supplied or avoided.
It cannot prove the private Codex/provider meter unless that meter is exposed by
the host.

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_ledger_task -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src/smavg/ledger.py src/smavg/cli.py
```

Result:

- Focused ledger/task tests passed: 6 tests.
- Full test suite passed: 75 tests after Work Mode was added.
- Compile check passed.
