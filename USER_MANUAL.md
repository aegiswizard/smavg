# Smavg 🐲 User Manual

Smavg helps ordinary users remove repeated baggage safely.

It can save disk space. It can also save AI context tokens.

The whole product can be remembered as:

```text
Scan. Report. Apply only when ready. Exact files stay available.
```

## The Main Idea

Most folders contain repeated structure:

- old versions of files
- repeated reports
- repeated notes
- repeated AI memories
- repeated skills and runbooks
- repeated workflow setup

Smavg scans locally and tells you what it found.

If there is strong repetition, Smavg can reduce it.

If there is weak repetition, Smavg says so.

## The Most Important Rule

Smavg does not ask AI to recreate exact files.

Exact files come from real bytes and are checked with hashes.

## Basic Daily Use

### See What Smavg Can Find

```bash
smavg scan
```

This is safe and read-only.

This should be the first command for almost everyone.

### Read The Latest Report

```bash
smavg report
```

This explains what Smavg found.

The report should make three things clear:

- where Smavg is useful
- where Smavg is weak
- what action, if any, the user can choose next

### See Savings

```bash
smavg status
```

This shows simple counters:

- tokens saved today
- tokens saved all time
- disk saved all time
- trust checks

### Apply Smavg To A Folder

```bash
smavg apply ./folder --out folder.smavg
```

This creates a verified archive. It does not delete your folder.

Smavg should feel boring here on purpose: archive, verify, restore, compare,
report.

## What "Tokens Saved" Means

Tokens are pieces of text used by AI models.

If an AI agent reads the same setup again and again, it wastes tokens.

Smavg creates a compact map first.

Example:

```text
Before: 100,000 repeated setup tokens
After: 5,000 Smavg tokens
Saved: 95,000 tokens
Reduction: 20x
```

These are Smavg-visible estimates, not a provider billing meter.

## What "Disk Saved" Means

Disk savings are measured from real file/archive sizes.

Example:

```text
Before: 1 GB folder
After: 100 MB archive
Reduction: 10x
```

## What "Weak Case" Means

A weak case means Smavg did not find strong useful repetition.

That is not failure. That is honest reporting.

For example, random photos, encrypted files, or already-compressed files may
not reduce much.

Smavg should say:

```text
No strong repetition found. Read directly or choose a narrower folder.
```

## What "Exact Expansion" Means

Smavg can give an AI agent a short brief first.

When exact detail matters, Smavg expands the real file:

```bash
smavg expand-context context.json README.md --out README.exact.md
```

Smavg checks size and SHA-256 before writing the output.

## What "Quarantine" Means

Quarantine means moving original data out of the active path after Smavg has
verified an archive and restored it successfully.

Quarantine is not deletion.

Same-disk quarantine does not free real disk space until the quarantine is
purged or moved off disk.

## What Smavg Will Not Do Silently

Smavg will not silently:

- delete your files
- upload your files
- send your files to a cloud AI model
- pretend weak data is a success
- count failed verification as a win

## Best First Folders To Try

Good first targets:

- old project versions
- repeated notes
- benchmark reports
- AI memory folders
- repeated workflow folders
- logs
- generated reports

Poor first targets:

- random photos
- encrypted data
- already-compressed zip/dmg archives
- one-off unique files

## Simple Success Rule

Smavg is successful when:

```text
Stored or supplied size is smaller.
Exact retrieval passes.
The report says honestly what happened.
```
