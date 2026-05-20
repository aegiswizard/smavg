# Smavg 🐲 CLI Reference

## Simple User Commands

### `smavg scan`

Finds useful folders and reports possible savings.

Safe: yes. Read-only.

```bash
smavg scan
smavg scan ./folder
```

### `smavg report`

Prints the latest simple report.

Safe: yes. Read-only.

```bash
smavg report
```

### `smavg status`

Shows saved today, saved all time, trust totals, and latest run.

Safe: yes. Read-only.

```bash
smavg status
```

### `smavg apply`

Safely packs a folder into a `.smavg` archive.

Safe: yes. It verifies before reporting success and does not delete source data.

```bash
smavg apply ./folder --out folder.smavg
```

## Context Commands

### `smavg context`

Builds a compact AI-readable repetition map.

```bash
smavg context ./folder --out context.md --json context.json
```

### `smavg expand-context`

Retrieves one exact file from a context map.

```bash
smavg expand-context context.json path/to/file.md --out exact.md
```

With receipt tracking:

```bash
smavg expand-context context.json path/to/file.md --out exact.md --receipt receipt.json
```

### `smavg receipt`

Creates or updates a receipt that records what Smavg supplied.

```bash
smavg receipt --context context.json --out receipt.json
```

## Agent Commands

### `smavg gate`

Creates a task packet for an AI agent.

```bash
smavg gate --source ./folder --task "Study this folder" --out-dir .smavg-gates
```

### `smavg work`

Runs a full Smavg-assisted work session.

```bash
smavg work start --source ./folder --task "Task"
smavg work expand README.md
smavg work note --role assistant --text "Used exact README."
smavg work end
```

## Archive Commands

### `smavg pack`

Creates a `.smavg` archive.

```bash
smavg pack ./folder --out folder.smavg
```

### `smavg verify`

Verifies an archive.

```bash
smavg verify folder.smavg
```

### `smavg restore`

Restores an archive.

```bash
smavg restore folder.smavg ./restored
```

### `smavg extract`

Extracts one exact file.

```bash
smavg extract folder.smavg path/to/file.txt --out file.txt
```

## Ledger Commands

### `smavg ledger report`

Shows saved tokens, saved disk, categories, and trust totals.

```bash
smavg ledger report
```

### `smavg ledger import-reports`

Imports Smavg JSON reports into the lifetime ledger.

```bash
smavg ledger import-reports ./benchmarks
```

## Surface Commands

### `smavg surfaces scan`

Inventories local skills, plugins, workflows, memories, and MCP/config summaries.

```bash
smavg surfaces scan
```

### `smavg surface-gauntlet`

Tests exact expansion and token reduction across discovered surfaces.

```bash
smavg surface-gauntlet
```

## Daemon Commands

```bash
smavg daemon init
smavg daemon once
smavg daemon status
smavg daemon service
```

The daemon scans and reports. It does not delete.

## Plugin Commands

```bash
smavg plugin build
smavg plugin verify
```

The plugin bundle wraps the local Smavg core.
