# Smavg Preflight v1

Date: 2026-05-16

This pass turns Smavg from a tool we call manually into an operating preflight
for repeated Codex work.

The goal is simple:

```text
Task starts
-> run smavg preflight
-> read compact context brief
-> expand exact files only when needed
-> do the work
-> record raw-vs-brief tokens
```

## Code Changes

- Added `src/smavg/preflight.py`.
- Added CLI command:
  `smavg preflight --workflow PROFILE` for named workflow capsules.
- Added CLI command:
  `smavg preflight --source PATH` for ordinary folders.
- Each preflight writes a timestamped run directory containing:
  - `context.md`
  - `context.json`
  - `preflight.md`
  - `preflight.json`
- The preflight summary records:
  - raw setup token estimate
  - brief token estimate
  - token reduction ratio
  - assessment
  - recommended exact expansion commands
  - strict use routine
- Added a unit test covering preflight output creation.
- Updated README with the preflight workflow.
- Updated local Smavg and X skills so future Codex sessions know to use
  preflight before repeated/token-sensitive work.

## Real Current Preflight Run

Command:

```bash
cd /Users/mac/smavg
PYTHONPATH=src python3 -m smavg.cli preflight \
  --workflow x-browsermcp \
  --out-dir /Users/mac/.codex/smavg-preflights \
  --run-id 2026-05-16-x-browsermcp-current \
  --budget 3000
```

Artifacts:

`/Users/mac/.codex/smavg-preflights/2026-05-16-x-browsermcp-current/`

Measured result:

| Item | Value |
| --- | ---: |
| Target | `workflow:x-browsermcp` |
| Files | 6 |
| Raw setup tokens estimate | 25,455 |
| Brief tokens estimate | 1,106 |
| Token reduction | 23.015x |
| Assessment | strong |

Recommended exact expansions:

| File | Estimated tokens | Result |
| --- | ---: | --- |
| `skills/codex/x-browser-automation/SKILL.md` | 1,281 | PASS |
| `memories/medium-term/x_browser_automation_workflow.md` | 2,417 | PASS |
| `memories/short-term/session_handoff.md` | 8,894 | available |

Exact expansion checks:

```bash
PYTHONPATH=src python3 -m smavg.cli expand-context \
  /Users/mac/.codex/smavg-preflights/2026-05-16-x-browsermcp-current/context.json \
  skills/codex/x-browser-automation/SKILL.md \
  --out /Users/mac/.codex/smavg-preflights/2026-05-16-x-browsermcp-current/exact/skills__codex__x-browser-automation__SKILL.md

cmp -s \
  /Users/mac/.codex/smavg-preflights/2026-05-16-x-browsermcp-current/exact/skills__codex__x-browser-automation__SKILL.md \
  /Users/mac/.codex/skills/x-browser-automation/SKILL.md
```

Result: PASS, 5,813 bytes verified.

```bash
PYTHONPATH=src python3 -m smavg.cli expand-context \
  /Users/mac/.codex/smavg-preflights/2026-05-16-x-browsermcp-current/context.json \
  memories/medium-term/x_browser_automation_workflow.md \
  --out /Users/mac/.codex/smavg-preflights/2026-05-16-x-browsermcp-current/exact/memories__medium-term__x_browser_automation_workflow.md

cmp -s \
  /Users/mac/.codex/smavg-preflights/2026-05-16-x-browsermcp-current/exact/memories__medium-term__x_browser_automation_workflow.md \
  /Users/mac/.codex/memories/medium-term/x_browser_automation_workflow.md
```

Result: PASS, 11,552 bytes verified.

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m compileall -q src tests
python3 /Users/mac/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  /Users/mac/.codex/skills/smavg-repetition-firewall
python3 /Users/mac/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  /Users/mac/.codex/skills/x-browser-automation
```

Result:

- 55 tests passed
- Compile check passed
- Smavg skill valid
- X skill valid

## Interpretation

Preflight v1 is the first concrete "Smavg mode" for our own Codex work. It
does not reduce tokens already loaded into a running conversation, and it does
not remove live BrowserMCP page snapshots. It reduces repeated setup context
from this point forward by making the agent read a compact verified map first,
then expand exact files only when the task needs them.

