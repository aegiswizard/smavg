# Smavg 🐲 Trust

Smavg is not trusted because it says it is safe.

Smavg is trusted because the claims are tested.

## Current Test Result

```text
100/100 tests passed.
16/16 trust-wall tests passed.
```

## Trust Wall Coverage

The trust-wall tests cover:

- malicious container paths
- bad payload metadata
- header hash mismatch
- extract overwrite refusal
- restore overwrite refusal
- mixed binary/empty/mode byte-perfect restore
- context SHA changes
- context path traversal
- receipt honesty
- failed ledger events not counted as wins
- safe-pack refusing archive-inside-source
- daemon read-only fingerprint preservation
- service file not loaded or started
- plugin Genesis-license/core-wrapper boundary
- license metadata consistency
- weak-case honesty

## Public Trust Facts

```text
Failures counted as wins: 0
Deletes performed by Smavg: 0
Exact restore or it does not count
```

## Exact Expansion

Context briefs are maps.

They do not replace exact files.

When exact detail matters, Smavg expands the real file and checks it.

## Benchmark Honesty

Smavg keeps strong results and weak results visible.

Strong examples:

- versioned code history: 617.239x
- Kimi MCP packages context: 1364.798x
- strict gate repeated work: 70.652x

Weak examples stay visible too.

That honesty is part of the product.
