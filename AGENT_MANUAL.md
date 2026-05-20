# Smavg 🐲 Agent Manual

This manual is for AI agents and AI CLI tools.

Smavg lets an agent avoid rereading repeated local context.

## Agent Rule

```text
Map first.
Exact expand second.
Verify always.
Never regenerate exact files with AI.
Never claim raw source was supplied if it was not.
```

## When To Use Smavg

Use Smavg before reading:

- large repeated folders
- project histories
- memory folders
- skills
- runbooks
- workflow instructions
- benchmark folders
- repeated reports

## Agent Workflow

1. Call Smavg before reading everything.
2. Read the Smavg brief.
3. Decide which exact files are needed.
4. Exact-expand those files.
5. Answer using the exact files when facts matter.
6. Record the X reduction.

## Task Gate

For a task:

```bash
smavg gate --source ./folder --task "Understand this project" --out-dir .smavg-gates
```

The gate packet includes:

- `gate.md`
- `gate.json`
- `context.md`
- `context.json`
- `receipt.md`
- `receipt.json`
- `exact/`

The agent should read `gate.md` first.

## Exact Expansion

When a file is needed:

```bash
smavg expand-context context.json path/to/file.md --out exact/file.md --receipt receipt.json
```

The receipt proves what Smavg supplied.

## Work Mode

Use Work Mode when Smavg is part of an active agent task:

```bash
smavg work start --source ./folder --task "Task description"
smavg work expand path/to/file.md
smavg work note --role assistant --text "What happened"
smavg work end
```

Work Mode connects:

- gate
- context brief
- receipt
- exact expansion
- visible task notes
- ledger event

## What The Agent Must Not Do

Do not:

- treat a brief as exact file content
- hallucinate file text
- say Smavg sent full raw source when it did not
- count a failed restore as a win
- hide weak cases

## Agent Success

The agent succeeds when:

```text
It reads less repeated setup.
It expands exact files when needed.
It answers with the same evidence as raw context.
It records the savings honestly.
```
