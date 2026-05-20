# Smavg Work Mode v1

Date: 2026-05-18

This pass turns Smavg into an operating loop for our own Codex work.

Before this, the pieces existed separately:

- `smavg gate`
- `smavg expand-context --receipt`
- `smavg task`
- `smavg ledger`

Work Mode connects them:

```text
work start -> gate + receipt + task counter
work expand -> exact file + receipt update
work note -> visible task token estimate
work end -> one task_session ledger event
```

## What Was Built

- New module:
  - `src/smavg/work.py`
- New CLI:
  - `smavg work start`
  - `smavg work expand`
  - `smavg work note`
  - `smavg work end`
  - `smavg work report`
- New tests:
  - `tests/test_work.py`
- Ledger integration:
  - `work end` records one `task_session` event.
  - Gate and receipt files are stored as artifacts.
  - The receipt is not separately counted as another win.

## Operating Pattern

```bash
PYTHONPATH=src python3 -m smavg.cli work start \
  --source /Users/mac/smavg \
  --task "Build the next Smavg improvement"

PYTHONPATH=src python3 -m smavg.cli work expand README.md

PYTHONPATH=src python3 -m smavg.cli work note \
  --role user \
  --text "User prompt text"

PYTHONPATH=src python3 -m smavg.cli work note \
  --role assistant \
  --text "Assistant result text"

PYTHONPATH=src python3 -m smavg.cli work end \
  --out ~/.smavg/work/reports/task.md
```

## Real Smoke

Command:

```bash
PYTHONPATH=src python3 -m smavg.cli work start \
  --source /Users/mac/smavg \
  --task "Smavg Work Mode v1 real smoke on the Smavg repo" \
  --id 2026-05-18-smavg-work-mode-v1-smoke \
  --budget 3000

PYTHONPATH=src python3 -m smavg.cli work expand README.md \
  --work-id 2026-05-18-smavg-work-mode-v1-smoke

PYTHONPATH=src python3 -m smavg.cli work note \
  --work-id 2026-05-18-smavg-work-mode-v1-smoke \
  --role user \
  --text "Please implement Smavg Work Mode v1 in full and verify it."

PYTHONPATH=src python3 -m smavg.cli work note \
  --work-id 2026-05-18-smavg-work-mode-v1-smoke \
  --role assistant \
  --text "Implemented Work Mode using gate, receipt, task session, exact expansion, and ledger accounting."

PYTHONPATH=src python3 -m smavg.cli work end \
  --work-id 2026-05-18-smavg-work-mode-v1-smoke \
  --out /Users/mac/.smavg/work/reports/2026-05-18-smavg-work-mode-v1-smoke.md
```

Artifacts:

- Gate:
  `/Users/mac/.smavg/work/runs/2026-05-18-smavg-work-mode-v1-smoke/gate.md`
- Context:
  `/Users/mac/.smavg/work/runs/2026-05-18-smavg-work-mode-v1-smoke/context.md`
- Receipt:
  `/Users/mac/.smavg/work/runs/2026-05-18-smavg-work-mode-v1-smoke/receipt.md`
- Work report:
  `/Users/mac/.smavg/work/reports/2026-05-18-smavg-work-mode-v1-smoke.md`

Result:

| Metric | Result |
| --- | ---: |
| Raw setup tokens | 192,405 |
| Brief tokens | 3,749 |
| Exact expansion tokens | 7,747 |
| Total Smavg-supplied tokens | 11,496 |
| Saved tokens | 180,909 |
| Reduction | 16.737x |
| Exact expansion | 1/1 |
| Full raw source supplied by Smavg | false |
| Visible user input tokens | 12 |
| Visible assistant output tokens | 18 |
| Ledger recorded | yes |

## Ledger Impact

Before this smoke, the all-time headline was:

```text
Tokens saved all time: 27,128,658
Tokens saved today: 0
```

After this smoke:

```text
Tokens saved today: 180,909
Tokens saved all time: 27,309,567
Repeated-work tokens saved all time: 58,456,133
Disk saved all time: 1,062,591,198 bytes
```

Lifetime after the smoke:

| Metric | Before | After | Reduction |
| --- | ---: | ---: | ---: |
| AI/context tokens | 28,155,063 | 845,829 | 33.287x |
| Repeated-work tokens | 59,239,323 | 783,190 | 75.639x |
| Storage disk bytes | 1,094,676,480 | 32,085,282 | 34.118x |

Trust after the smoke:

| Metric | Result |
| --- | ---: |
| Ledger events | 39 |
| Exact expansion | 46/46 |
| Evidence tasks | 64/64 |
| Restore | 60/61 |
| Verify | 60/61 |
| Failures counted as wins | 0 |

## Truth Boundary

Work Mode records Smavg-supplied context and visible task text estimates. It
does not claim private provider billing-meter visibility.

The key product shift is this:

```text
Smavg now has a daily-use loop.
The saved-today counter moves when real work ends.
```

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_work -v
PYTHONPATH=src python3 -m unittest tests.test_ledger_task tests.test_work -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src/smavg tests
```

Result:

- Work Mode test passed: 1/1.
- Focused ledger/work tests passed: 7/7.
- Full suite passed: 75/75.
- Compile check passed.
