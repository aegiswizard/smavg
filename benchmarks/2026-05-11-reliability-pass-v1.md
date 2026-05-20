# Smavg Reliability Pass v1

Date: 2026-05-11

This pass tested whether `smavg context` can act as a trustworthy repetition
firewall for AI agents across more real local folders. The target was not a new
best compression headline. The target was range, honest weak-case reporting,
agent-usable briefs, exact expansion, and bounded memory.

## Code Changes

- Added context usefulness assessments: `excellent`, `strong`, `useful`,
  `weak`, and `no_text`.
- Added family token coverage so a high ratio does not hide weak structure.
- Added recommended exact files to expand, with path-role hints such as Smavg
  runbook, session handoff, current focus, README, benchmark, and format spec.
- Added `smavg context --budget N` as an approximate brief-size mode. If the
  rendered brief exceeds the requested budget, Smavg now says so explicitly.
- Added CLI output for assessment, recommendation, family coverage, and top
  exact expansion recommendations.
- Fixed no-text CLI output from `Nonex` to `n/a`.
- Added tests for weak/no-repetition reporting and high-signal file
  recommendations.

## Real Context Range

Raw Markdown/JSON outputs were saved outside the repository under:

`/Users/mac/.codex/smavg-private-benchmarks/2026-05-11-reliability-v1/`

| Source | Files | Text/Binary | Logical bytes | Raw tokens | Brief tokens | Ratio | Families | Coverage | Assessment | Time | Max RSS |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| `/Users/mac/.kimi/mcp-packages` | 5,207 | 4,753 / 454 | 71,793,373 | 6,394,079 | 4,685 | 1364.798x | 268 | 62.94% | excellent | 8.96s | 87.1 MB |
| `/Users/mac/.codex/memories` | 83 | 83 / 0 | 895,020 | 204,137 | 2,672 | 76.399x | 3 | 94.46% | excellent | 0.46s | 21.4 MB |
| `/Users/mac/smavg/src/smavg` | 15 | 15 / 0 | 276,912 | 58,821 | 991 | 59.355x | 1 | 100.0% | excellent | 0.22s | 18.8 MB |
| `/Users/mac/smavg` | 49 | 49 / 0 | 476,520 | 106,017 | 2,337 | 45.365x | 4 | 88.5% | strong | 0.26s | 18.5 MB |
| `/Users/mac/.kimi/skills` | 49 | 48 / 1 | 307,836 | 73,352 | 2,592 | 28.299x | 3 | 97.41% | strong | 0.32s | 19.4 MB |
| Patent research folder | 8 | 8 / 0 | 81,004 | 19,554 | 1,211 | 16.147x | 1 | 76.24% | strong | 0.19s | 17.3 MB |
| `/Users/mac/smavg/tests` | 10 | 10 / 0 | 50,623 | 10,475 | 920 | 11.386x | 1 | 100.0% | strong | 0.18s | 17.0 MB |
| `/Users/mac/smavg/benchmarks` | 9 | 9 / 0 | 36,315 | 9,571 | 1,669 | 5.735x | 1 | 100.0% | useful | 0.18s | 17.0 MB |
| Mixed unrelated real files | 6 | 5 / 1 | 203,479 | 12,176 | 589 | 20.672x | 0 | 0.0% | weak | 0.16s | 16.8 MB |
| `/Users/mac/.kimi/bin` | 1 | 0 / 1 | 4,442,892 | 0 | 333 | n/a | 0 | 0.0% | no_text | 0.16s | 20.7 MB |

The mixed unrelated corpus was assembled from real local files only:
`/bin/ls`, `LICENSE`, `pyproject.toml`, `src/smavg/context.py`,
`patent_matrix.csv`, and `sources.json`. It intentionally had no repeated
family. Smavg reported it as `weak` even though the brief itself was shorter
than the raw token estimate, because family coverage was 0.0%.

## Exact Expansion Checks

Each check used `smavg expand-context ...` followed by `cmp -s` against the
source file.

| Context | Expanded file | Bytes | Result |
| --- | --- | ---: | --- |
| Codex memories | `medium-term/smavg_runbook.md` | 33,404 | PASS |
| Kimi skills | `kimi-code-docs/SKILL.md` | 37,593 | PASS |
| Smavg repo | `src/smavg/context.py` | 29,522 | PASS |
| Smavg benchmarks | `2026-05-11-history-pack-v4.md` | 6,256 | PASS |
| Kimi MCP packages | `scout-mcp/.venv/lib/python3.13/site-packages/idna/uts46data.py` | 202,713 | PASS |
| Binary-only folder | `rg` | 4,442,892 | PASS |
| Mixed unrelated real files | `context.py` | 29,522 | PASS |

## Agent Brief-Use Check

One separate agent was given only the generated Codex memories context brief
excerpt and no filesystem access. It was asked which exact files should be
expanded.

Result: PASS.

- Smavg runbook: `medium-term/smavg_runbook.md`
- Latest handoff/current state: `short-term/session_handoff.md`
- Current focus: `short-term/current_focus.md`
- Line-level facts: request exact expansion first

This is the intended trust model. The brief is the map; exact expansion is the
truth source for citations and details.

## Budget Check

Command:

```bash
PYTHONPATH=src python3 -m smavg.cli context /Users/mac/.codex/memories \
  --budget 1000 \
  --out codex-memories-context-budget1000.md \
  --json codex-memories-context-budget1000.json
```

Observed:

- Brief tokens: 1,423
- Token reduction: 143.455x
- Assessment: `excellent`
- Recommendation included: `Brief is above the requested 1000-token budget; use a higher budget or narrower folder.`

The budget flag is approximate in this pass. It reduces rendered sections and
warns honestly if the brief still exceeds the requested limit.

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m compileall -q src tests
```

Result:

- 52 tests passed
- Compile check passed

## Interpretation

The reliability pass supports the current product direction:

Smavg is strongest when a folder contains repeated structures that an AI agent
would otherwise read again and again. It now also gives honest responses when
that condition is not present.

The most important result is not the highest ratio. It is that the same command
can report `excellent`, `strong`, `useful`, `weak`, or `no_text` based on real
folder shape, while exact expansion remains byte-perfect.
