# Smavg 🐲 Daemon

The Smavg daemon is the future quiet background helper.

Daemon v1 is conservative:

- scans
- reports
- writes status
- performs no delete
- performs no quarantine
- performs no automatic cleanup
- performs no upload

## Initialize

```bash
smavg daemon init
```

## Run Once

```bash
smavg daemon once
```

## Status

```bash
smavg daemon status
```

## Service File

```bash
smavg daemon service
```

This writes a service-manager file. It does not load or start it.

## Promise

```text
Smavg daemon is a quiet scanner and reporter first.
Cleanup requires explicit user approval.
```
