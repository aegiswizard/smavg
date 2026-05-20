# Smavg Public Release Checklist

Use this before publishing or updating Smavg.

## User Clarity

- README explains Smavg in plain language.
- `START_HERE.md` gives a nontechnical first path.
- `QUICKSTART.md` gives copy-paste commands.
- `INSTALL.md` explains zip and GitHub installs.
- The first commands are `smavg scan`, `smavg report`, and `smavg status`.

## Product Focus

- The top-level promise is consistent:

```text
Remove repetition safely, then retrieve exact information on demand.
```

- Storage, AI context, skill, MCP, plugin, and daemon docs all point back to the
  same local core.
- Advanced surfaces do not distract from the first user flow.

## Safety

- Scan/report/status are read-only.
- Apply verifies before cleanup.
- Quarantine is not deletion.
- Smavg does not upload user data.
- Smavg does not ask AI to recreate exact files.
- Failed verification is not counted as success.

## Verification

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -q
PYTHONPATH=src python3 -m compileall -q src tests
scripts/verify-release.sh
```

Expected:

```text
100/100 tests passed
compileall passed
release verification passed
```

## Package Check

After building `smavg.zip`, run:

```bash
unzip -t /Users/mac/smavg.zip
shasum -a 256 /Users/mac/smavg.zip
```

Record the size and SHA-256 in the release notes.

## Public Honesty

- Keep weak cases visible.
- Keep benchmark reports dated.
- Label token numbers as Smavg-visible estimates.
- Label storage numbers as measured bytes.
- Do not describe the license as plain MIT.
- Link `LICENSE_SUMMARY.md`, `LEGAL_NOTES.md`, `CONTRIBUTOR_TERMS.md`, and
  `TRADEMARK.md` from README.
- Make clear that commercial-scale thresholds mean attribution by default, not
  automatic payment.

## Launch State

Smavg is ready to publish when:

- users can understand it in one minute
- users can install it in five minutes
- users can run a safe scan first
- developers can verify the tests
- agents can use the skill/MCP/plugin docs
- the zip integrity check passes
