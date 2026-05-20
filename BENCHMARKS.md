# Smavg 🐲 Benchmarks

Token numbers are Smavg-visible estimates. Storage numbers are real measured
bytes.

## Storage

| Test | Before | After | Result |
|---|---:|---:|---:|
| Versioned code history | 171,156,036 bytes | 277,293 bytes | 617.239x |
| Mixed history corpus | 46,885,286 bytes | 164,556 bytes | 284.920x |
| Safe-pack cleanup archive | 176,128 disk bytes | 16,384 bytes | 10.75x |
| Benchmark folder archive | 72,558 bytes | 33,142 bytes | 2.189x |

## AI Context

| Test | Before | After | Result |
|---|---:|---:|---:|
| Kimi MCP packages | 6,394,079 tokens | 4,685 tokens | 1364.798x |
| Codex memories budget mode | 204,137 tokens | 1,423 tokens | 143.455x |
| Codex memories v1 | 203,506 tokens | 1,595 tokens | 127.590x |
| Smavg source folder | 58,821 tokens | 991 tokens | 59.355x |
| Smavg repo context | 106,017 tokens | 2,337 tokens | 45.365x |
| Kimi skills | 73,352 tokens | 2,592 tokens | 28.299x |
| Patent research folder | 19,554 tokens | 1,211 tokens | 16.147x |

## Agent Workflow

| Test | Before | After | Result |
|---|---:|---:|---:|
| Strict gate repeated work | 9,943,296 tokens | 140,736 tokens | 70.652x |
| Codex workload repeated path | 9,828,987 tokens | 129,352 tokens | 75.986x |
| Codex A/B evidence path | 9,219,172 tokens | 139,495 tokens | 66.090x |
| X BrowserMCP repeated setup | 71,844 tokens | 4,121 tokens | 17.434x |
| Hacker News repeated setup | 72,057 tokens | 4,554 tokens | 15.823x |
| Work Mode Smavg repo task | 192,405 tokens | 11,496 tokens | 16.737x |

## Surface / Skill / MCP

| Test | Before | After | Result |
|---|---:|---:|---:|
| Surface registry brief | 970,368 tokens | 30,953 tokens | 31.350x |
| Surface gauntlet first-time | 970,368 tokens | 268,177 tokens | 3.618x |
| Surface gauntlet repeated | 2,911,104 tokens | 268,177 tokens | 10.855x |
| Daemon surface scan | 1,001,735 tokens | 31,141 tokens | 32.168x |

## Lifetime Ledger Snapshot

| Area | Before | After | Result |
|---|---:|---:|---:|
| AI/context | 29,125,431 tokens | 1,114,006 tokens | 26.145x |
| Repeated work | 59,239,323 tokens | 783,190 tokens | 75.639x |
| Storage disk | 1,094,500,352 bytes | 32,068,898 bytes | 34.13x |

## Notes

These benchmark summaries point to public reports in `benchmarks/`.

They are not synthetic promises. They are measured results from real local
Smavg runs. Weak cases remain part of the public record.
