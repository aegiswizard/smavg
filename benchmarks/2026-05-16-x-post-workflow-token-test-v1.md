# Smavg X Post Workflow Token Test v1

Date: 2026-05-16

This test measures Smavg as a repetition firewall for repeated X posting work
through BrowserMCP. The goal is not to compress live X page snapshots. The goal
is to stop paying the setup-token cost repeatedly for the same X skill,
runbook, safety rules, and workflow memory.

## Real BrowserMCP Action

BrowserMCP was connected and used to publish one real X post from the `@smavgs`
account.

Post URL:

`https://x.com/smavgs/status/2055607371880358384`

Posted text:

> Testing a live BrowserMCP posting workflow from Codex. Small real-world check: connected, drafted, and posted through the browser. Building reliable agent workflows one verified step at a time.

Verification:

- BrowserMCP compose page opened at `https://x.com/compose/post`.
- BrowserMCP typed the post text into the X compose textbox.
- BrowserMCP clicked the X `Post` button.
- X returned the visible alert: `Your post was sent.`
- BrowserMCP later opened the post URL and the post page showed the exact text.

No additional public posts were made for this token test.

## Smavg Workflow Context Measurement

Command:

```bash
PYTHONPATH=src python3 -m smavg.cli workflow-context x-browsermcp \
  --out /Users/mac/.codex/smavg-private-benchmarks/2026-05-16-x-post-workflow-token-test-v1/x-browsermcp-context.md \
  --json /Users/mac/.codex/smavg-private-benchmarks/2026-05-16-x-post-workflow-token-test-v1/x-browsermcp-context.json \
  --budget 3000
```

Raw local artifacts:

`/Users/mac/.codex/smavg-private-benchmarks/2026-05-16-x-post-workflow-token-test-v1/`

Measured workflow profile:

| Item | Value |
| --- | ---: |
| Workflow profile | `x-browsermcp` |
| Files included | 6 / 6 |
| Logical bytes | 105,658 |
| Raw setup tokens estimate | 23,948 |
| Smavg brief tokens estimate | 1,104 |
| Brief-only reduction | 21.692x |
| Families detected | 1 |
| Family token coverage | 100.0% |
| Assessment | strong |

Recommended exact expansions:

| File | Estimated tokens | Exact expansion |
| --- | ---: | --- |
| `skills/codex/x-browser-automation/SKILL.md` | 1,032 | PASS |
| `memories/medium-term/x_browser_automation_workflow.md` | 1,985 | PASS |
| `memories/medium-term/workflows_and_runbooks.md` | 8,196 | available |
| `memories/short-term/session_handoff.md` | 8,363 | available |
| `memories/short-term/current_focus.md` | 3,585 | available |
| `memories/long-term/collaboration_preferences.md` | 787 | available |

Exact expansion checks:

```bash
PYTHONPATH=src python3 -m smavg.cli expand-context \
  /Users/mac/.codex/smavg-private-benchmarks/2026-05-16-x-post-workflow-token-test-v1/x-browsermcp-context.json \
  skills/codex/x-browser-automation/SKILL.md \
  --out /Users/mac/.codex/smavg-private-benchmarks/2026-05-16-x-post-workflow-token-test-v1/exact-x-skill.md

cmp -s \
  /Users/mac/.codex/smavg-private-benchmarks/2026-05-16-x-post-workflow-token-test-v1/exact-x-skill.md \
  /Users/mac/.codex/skills/x-browser-automation/SKILL.md
```

Result: PASS, 4,905 bytes verified.

```bash
PYTHONPATH=src python3 -m smavg.cli expand-context \
  /Users/mac/.codex/smavg-private-benchmarks/2026-05-16-x-post-workflow-token-test-v1/x-browsermcp-context.json \
  memories/medium-term/x_browser_automation_workflow.md \
  --out /Users/mac/.codex/smavg-private-benchmarks/2026-05-16-x-post-workflow-token-test-v1/exact-x-runbook.md

cmp -s \
  /Users/mac/.codex/smavg-private-benchmarks/2026-05-16-x-post-workflow-token-test-v1/exact-x-runbook.md \
  /Users/mac/.codex/memories/medium-term/x_browser_automation_workflow.md
```

Result: PASS, 9,743 bytes verified.

## Token Comparison

This comparison measures stable workflow setup only. Live X snapshots, current
timeline state, compose state, and post-specific writing are still real-time
BrowserMCP work and are common to both paths.

Assumption for the repeated-work baseline:

- Without Smavg, the agent reloads the full X workflow corpus before each post.
- With Smavg, the agent reads the compact workflow brief once, then expands the
  exact X skill and exact X runbook once for the working session.

| Scenario | Setup tokens |
| --- | ---: |
| Raw setup for one X post task | 23,948 |
| Raw setup repeated for 3 X post tasks | 71,844 |
| Smavg brief once | 1,104 |
| Smavg brief + exact X skill + exact X runbook once | 4,121 |

Measured reductions:

| Comparison | Reduction |
| --- | ---: |
| Brief-only setup compression | 21.692x |
| Practical 3-post setup reduction | 17.434x |
| Conservative raw-once vs Smavg exact setup | 5.811x |
| 10 repeated posts using the same Smavg setup | 58.112x |

## Interpretation

Smavg is useful here because repeated BrowserMCP posting work keeps reusing the
same operating knowledge:

- X BrowserMCP skill instructions
- X posting safety rules
- X runbook
- current handoff and focus notes
- collaboration preferences

Smavg does not remove the need to inspect the live page. It removes the repeated
setup baggage around the live page. For one post, the end-to-end saving can be
modest. For repeated posting workflows, the stable setup reduction is already
measured at 17.434x for three tasks and grows as more tasks reuse the same
brief and exact expansions.

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m compileall -q src tests
```

Result:

- 54 tests passed
- Compile check passed

