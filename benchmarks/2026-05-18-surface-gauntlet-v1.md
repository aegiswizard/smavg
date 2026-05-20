# Smavg Surface Registry + Gauntlet v1

Date: 2026-05-18

This run tested Smavg as the operating layer for local Codex/agent surfaces:
skills, plugin-cache skills, workflow profiles, Codex memories, the Smavg repo,
and sanitized MCP/config summaries.

## Real Local Result

- Surfaces inventoried: 227
- Surface types: 62 local skills, 135 plugin-cache skills, 18 plugin bundles,
  6 workflow profiles, 4 MCP/config files, 1 Smavg MCP server, 1 project
- Context groups tested: 12
- Verified groups: 12/12
- Useful groups: 10/12
- Weak/no-benefit groups: 2/12
- Exact expansions: 35/35
- Configured but uncalled surfaces: 4
- Full raw source supplied by Smavg: false

## Token Result

- Registry brief-only path: 970,368 raw tokens -> 30,953 brief tokens, 31.350x
- Gauntlet first-time path with representative exact expansions:
  970,368 raw tokens -> 268,177 Smavg-supplied tokens, 3.618x
- Repeated-work path:
  2,911,104 raw tokens -> 268,177 Smavg-supplied tokens, 10.855x

## Honest Weak Cases

- Agents local skills: exact expansion 2/2, but first-time path was weak
  because the surface is small.
- Sanitized MCP/config summaries: exact expansion 3/3, but token reduction is
  not the goal; secret-safe inventory is the goal.

## Artifacts

- Report JSON:
  `/Users/mac/.codex/smavg-private-benchmarks/2026-05-18-surface-gauntlet-v1/results.json`
- Report Markdown:
  `/Users/mac/.codex/smavg-private-benchmarks/2026-05-18-surface-gauntlet-v1/report.md`
- Registry JSON:
  `/Users/mac/.codex/smavg-private-benchmarks/2026-05-18-surface-gauntlet-v1/registry/surfaces.json`

## Trust Boundary

This proves local inventory, local context reduction, and exact expansion for
representative files. It does not claim account-side app access or current
session tool callability for external MCP/app surfaces unless the host exposes
that as a local callable signal.
