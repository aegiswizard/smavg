# Smavg Daemon + Plugin v1

Date: 2026-05-20

This pass made Smavg usable as a safe local daemon surface and a thin
skill/MCP/plugin bundle while keeping one verified core underneath.

## What Was Built

- `smavg daemon init`
- `smavg daemon once`
- `smavg daemon run`
- `smavg daemon status`
- `smavg daemon service`
- `smavg plugin build`
- `smavg plugin verify`
- MCP tools for status, autopilot scan, daemon once/status, and plugin
  build/verify.

## Real Local Smoke

Plugin bundle:

- Bundle: `/Users/mac/.smavg/plugin/smavg-agent`
- Skill: `/Users/mac/.smavg/plugin/smavg-agent/skills/smavg-repetition-firewall/SKILL.md`
- MCP config: `/Users/mac/.smavg/plugin/smavg-agent/mcp/smavg-mcp.json`
- Verify: `PASS`
- Checks: `11/11`
- Core policy: `wrap-smavg-core-only`

Daemon config:

- Config: `/Users/mac/.smavg/daemon/config.json`
- Root: `/Users/mac/smavg`
- Interval: `21600` seconds
- Budget: `3000` tokens
- Max depth: `1`
- Max dirs: `12`
- Network required: `false`
- Apply enabled: `false`
- Delete enabled: `false`

Daemon run:

- Run id: `2026-05-20-daemon-plugin-v1`
- Report: `/Users/mac/.smavg/daemon/runs/2026-05-20-daemon-plugin-v1/daemon.md`
- Autopilot report: `/Users/mac/.smavg/daemon/autopilot/runs/2026-05-20-daemon-plugin-v1/report.md`
- Directory candidates: `5`
- Workflow candidates: `6`
- Surfaces inventoried: `227`
- Surface context groups: `12`
- Best directory token reduction: `106.62x`
- Best workflow token reduction: `28.814x`
- Surface registry reduction: `32.168x`
- Surface raw tokens estimate: `1,001,735`
- Surface brief tokens estimate: `31,141`
- Cleanup performed: `false`
- Archive performed: `false`
- Quarantine performed: `false`
- Delete performed: `false`

Service file:

- File: `/Users/mac/.smavg/daemon/com.aegiswizard.smavg.daemon.plist`
- Platform: `launchd`
- Written: `true`
- Loaded/enabled/started: `false`

## Verification

- Unit tests: `84/84 PASS`
- Compile check: `PASS`
- Plugin verify: `11/11 PASS`
- Daemon state written: `PASS`
- Source deleted: `NO`
- Source quarantined: `NO`
- Failures counted as wins: `0`

## Truth Boundary

Daemon v1 is read-only. It scans, reports, and writes state. It does not delete,
quarantine, archive active paths, or send data off-machine. The plugin bundle
contains wrapper instructions and MCP config only; all behavior calls the local
Smavg CLI/MCP core.
