# Smavg 🐲 Security

Smavg handles local files. Treat safety seriously.

## Report Security Issues

Email: smavg@myyahoo.com

Please include:

- affected version or commit
- operating system
- reproduction steps
- expected behavior
- actual behavior

Do not include secrets.

## Current Safety Scope

Smavg currently focuses on local archive/context safety:

- path traversal rejection
- payload bounds checks
- checksum verification
- exact restore checks
- overwrite refusal in sensitive paths
- no silent delete
- no cloud upload in the core

## Out Of Scope For Current Prototype

- filesystem kernel hardening
- multi-user service hardening
- signed release binaries
- enterprise policy controls

These belong later, after the core remains trusted.
