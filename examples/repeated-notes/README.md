# Repeated Notes Example

This folder shows the kind of repeated notes Smavg can summarize for an AI
agent.

Try:

```bash
smavg context examples/repeated-notes --out /tmp/repeated-notes.md --json /tmp/repeated-notes.json
```

Then read `/tmp/repeated-notes.md`.

If exact detail is needed:

```bash
smavg expand-context /tmp/repeated-notes.json week-002.md --out /tmp/week-002.md
```
