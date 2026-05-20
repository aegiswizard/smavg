# Smavg 🐲 MCP

Smavg MCP lets AI agents call Smavg as a local tool.

The MCP server does not replace the Smavg core. It exposes the same local
commands through an agent-friendly interface.

## Start The MCP Server

```bash
python3 -m smavg.mcp_server
```

or:

```bash
smavg-mcp
```

## Example MCP Config

See [mcp/smavg-mcp.json](mcp/smavg-mcp.json).

## Main Tools

Typical tools exposed by Smavg MCP:

- `smavg_preflight`
- `smavg_context`
- `smavg_expand`
- `smavg_verify_archive`
- `smavg_report_archive`
- `smavg_scan`
- `smavg_status`
- `smavg_daemon_once`
- `smavg_daemon_status`
- `smavg_plugin_build`
- `smavg_plugin_verify`
- `smavg_surface_scan`
- `smavg_surface_gauntlet`

## Agent Rule

Agents should:

1. call Smavg first for repeated context
2. read the brief
3. expand exact files only when needed
4. verify exact retrieval
5. record token savings

## Truth Boundary

Smavg MCP can prove what Smavg supplied.

It cannot prove what unrelated app history or non-Smavg tools supplied to the
model.
