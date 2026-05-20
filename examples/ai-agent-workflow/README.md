# AI Agent Workflow Example

This example shows how an AI agent should use Smavg.

The agent should not read every file first.

The agent should:

1. build a Smavg context
2. read the brief
3. expand exact files only when needed
4. record the saved tokens

Try:

```bash
smavg gate --source examples/ai-agent-workflow --task "Understand this workflow" --out-dir /tmp/smavg-agent-gate
```
