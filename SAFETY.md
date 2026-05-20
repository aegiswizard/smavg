# Smavg 🐲 Safety

Smavg is designed around safety first.

## Read-Only By Default

These commands are read-only:

- `smavg scan`
- `smavg report`
- `smavg status`
- `smavg context`
- `smavg ledger report`
- `smavg daemon once`

## No Silent Deletes

Smavg does not silently delete user data.

Safe-pack and apply verify before reporting success.

## Quarantine Is Not Deletion

Quarantine means moving original data out of the active path.

Same-disk quarantine does not free real disk space until the quarantine is
purged or moved off disk.

## Exact Restore Rule

Exact restore must pass or it does not count.

Smavg checks:

- paths
- sizes
- SHA-256 hashes
- archive payload integrity
- restored tree comparison where applicable

## AI Safety Rule

Smavg does not ask AI to recreate exact files.

For exact facts, the agent must expand exact files.

## Honest Weak Cases

If Smavg cannot reduce a folder well, it says so.

Weak reports are part of trust.

## Failed Events

Failed verification events remain visible, but they are not counted as
benefits.

This rule is covered by the trust-wall test suite.
