---
name: smavg-repetition-firewall
description: Use Smavg to reduce repeated AI context, exact-expand files, verify archives, and report token or disk savings.
---

# Smavg Repetition Firewall

Use Smavg before reading repeated local context.

## Rules

- Map first.
- Exact expand second.
- Verify always.
- Count X saved.
- Never regenerate exact files with AI.
- Never claim raw source was supplied if Smavg supplied only a brief.

## Commands

```bash
smavg context ./folder --out context.md --json context.json
smavg expand-context context.json path/to/file.md --out exact.md
smavg status
```

## When Facts Matter

Use exact expansion before quoting, citing, editing, or relying on file content.

## Boundary

This skill is a wrapper instruction. It does not replace Smavg core
verification.
