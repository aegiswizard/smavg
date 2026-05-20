# Smavg 🐲 Skill

Use this skill when an AI agent needs to reduce repeated context, read Smavg
briefs, exact-expand files, verify archives, or report Smavg savings.

## Core Rules

- Map first.
- Exact expand second.
- Verify always.
- Count X saved.
- Never regenerate exact file contents with AI.
- Never claim raw source was supplied when Smavg supplied only a brief.

## When To Use

Use Smavg before reading:

- repeated project history
- AI memories
- skills
- runbooks
- workflow notes
- repeated reports
- benchmark folders
- large text/code folders

## Basic Flow

```bash
smavg context ./folder --out context.md --json context.json
```

Read `context.md`.

When exact detail is needed:

```bash
smavg expand-context context.json path/to/file.md --out exact.md
```

## Work Flow

```bash
smavg work start --source ./folder --task "Task"
smavg work expand path/to/file.md
smavg work end
```

## Important

The skill does not replace Smavg core verification. It tells the agent how to
use the local Smavg core correctly.
