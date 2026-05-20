# Smavg Workflow Context v1

Date: 2026-05-11

This pass tests Smavg as a practical context capsule for repetitive agent
workflows. The first target is BrowserMCP-style operating work, where an agent
normally rereads the same skill instructions, memory runbooks, safety rules,
and current handoff notes before each task.

The goal is not to compress live browser state. The goal is to stop repeatedly
spending tokens on stable workflow knowledge. Exact files stay available through
`smavg expand-context`.

## Code Changes

- Added `smavg workflow-context`.
- Added named workflow profiles:
  `x-browsermcp`, `reddit-browsermcp`, `linkedin-browsermcp`,
  `producthunt-browsermcp`, `hackernews-browsermcp`, and
  `threads-browsermcp`.
- Added path-set context reports. A context can now cover selected real files
  spread across different directories, while exact expansion verifies and reads
  the original source file.
- Added `source_kind`, `source_roots`, per-file `source_path`, and missing
  source counts to context JSON.
- Added deterministic recommendation boosts for workflow-specific BrowserMCP
  skills and workflow runbooks.
- Added tests for file-map context expansion and changed-source rejection.

## Commands

```bash
PYTHONPATH=src python3 -m smavg.cli workflow-context --list

PYTHONPATH=src python3 -m smavg.cli workflow-context x-browsermcp \
  --out x-browsermcp-context.md \
  --json x-browsermcp-context.json \
  --budget 3000

PYTHONPATH=src python3 -m smavg.cli expand-context \
  x-browsermcp-context.json \
  skills/codex/x-browser-automation/SKILL.md \
  --out exact-skill.md
```

## Real Workflow Range

Raw Markdown/JSON outputs were saved outside the repository under:

`/Users/mac/.codex/smavg-private-benchmarks/2026-05-11-workflow-context-v1/`

| Workflow | Available / Requested Files | Missing | Logical bytes | Raw tokens | Brief tokens | Ratio | Families | Coverage | Assessment | Time | Max RSS |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| `threads-browsermcp` | 6 / 7 | 1 | 101,301 | 23,201 | 1,005 | 23.086x | 0 | 0.0% | weak | 0.19s | 17.6 MB |
| `producthunt-browsermcp` | 7 / 7 | 0 | 107,734 | 24,599 | 1,204 | 20.431x | 1 | 100.0% | strong | 0.20s | 17.8 MB |
| `x-browsermcp` | 6 / 6 | 0 | 97,947 | 22,097 | 1,100 | 20.088x | 1 | 100.0% | strong | 0.18s | 17.3 MB |
| `linkedin-browsermcp` | 7 / 7 | 0 | 109,262 | 24,392 | 1,237 | 19.719x | 1 | 100.0% | strong | 0.21s | 17.7 MB |
| `reddit-browsermcp` | 7 / 7 | 0 | 108,942 | 24,824 | 1,331 | 18.651x | 1 | 100.0% | strong | 0.21s | 18.9 MB |
| `hackernews-browsermcp` | 7 / 7 | 0 | 101,764 | 23,186 | 1,254 | 18.490x | 1 | 100.0% | strong | 0.20s | 17.8 MB |

Threads is intentionally counted as a weak result because the Kimi mirror skill
file was missing and family coverage was 0.0%. It still produced a compact
index and exact expansion worked for included files.

## X BrowserMCP Capsule

The X profile includes:

- `skills/codex/x-browser-automation/SKILL.md`
- `memories/medium-term/x_browser_automation_workflow.md`
- `memories/medium-term/workflows_and_runbooks.md`
- `memories/short-term/current_focus.md`
- `memories/short-term/session_handoff.md`
- `memories/long-term/collaboration_preferences.md`

Top recommended expansions after deterministic scoring:

1. `skills/codex/x-browser-automation/SKILL.md`
2. `memories/medium-term/x_browser_automation_workflow.md`
3. `memories/medium-term/workflows_and_runbooks.md`
4. `memories/short-term/session_handoff.md`
5. `memories/short-term/current_focus.md`

This is the desired behavior: the brief tells the agent which exact files to
expand before operating, instead of forcing it to reread all workflow material
every turn.

## Exact Expansion Checks

Each check used `smavg expand-context ...` followed by `cmp -s` against the
original source file.

| Context | Expanded file | Bytes | Result |
| --- | --- | ---: | --- |
| `x-browsermcp` | `skills/codex/x-browser-automation/SKILL.md` | 4,905 | PASS |
| `x-browsermcp` | `memories/medium-term/x_browser_automation_workflow.md` | 9,743 | PASS |
| `reddit-browsermcp` | `skills/codex/reddit-browsermcp/SKILL.md` | 9,365 | PASS |
| `threads-browsermcp` | `skills/codex/threads-browsermcp/SKILL.md` | 8,119 | PASS |

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m compileall -q src tests
```

Result:

- 54 tests passed
- Compile check passed

## Interpretation

Workflow context is a practical near-term Smavg use case. It reduces repeated
workflow setup context by roughly 18x-23x on the measured BrowserMCP profiles
while keeping exact source files available.

This does not replace live BrowserMCP page inspection. The page still must be
observed in real time. Smavg reduces the stable operating knowledge around the
task: skill instructions, runbooks, safety boundaries, handoffs, and user
collaboration preferences.
