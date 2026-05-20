# Smavg 🐲 Plugin

The Smavg plugin bundle helps AI tools discover and use Smavg.

It is a wrapper, not a second implementation.

All real behavior stays in the local Smavg core.

## Build

```bash
smavg plugin build
```

## Verify

```bash
smavg plugin verify
```

## Bundle Contents

The generated bundle contains:

- manifest
- README
- Smavg skill
- MCP config
- Codex example
- Kimi notes
- Gemini notes

## Hard Rule

The plugin must not fork compression logic.

It must call the local Smavg CLI/MCP core.

## Why This Matters

This lets Codex, Kimi, Gemini, Claude-style tools, and future agents use Smavg
without each one needing a separate implementation.
