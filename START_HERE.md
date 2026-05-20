# Start Here

Smavg 🐲 is for one simple problem:

```text
Computers and AI agents keep reading and storing the same information again.
```

Smavg finds that repetition, reports it honestly, and keeps exact files
available when needed.

## The Plain Version

Smavg does two useful things:

- saves disk space when folders contain repeated or versioned files
- saves AI tokens when agents keep rereading the same skills, memories,
  runbooks, reports, and setup files

It does this locally.

It does not need a cloud account.

It does not need API keys.

It does not use AI to recreate exact files.

## The First Safe Command

Run:

```bash
smavg scan
```

This is read-only.

It does not delete, move, upload, or change your files.

## The First Report

Then run:

```bash
smavg report
```

Smavg will tell you:

- what it found
- where repetition looks useful
- where Smavg is weak
- what may save disk
- what may save AI tokens
- what needs exact verification

## The Simple Dashboard

Run:

```bash
smavg status
```

This shows the numbers people can remember:

```text
Tokens saved today
Tokens saved all time
Disk saved all time
Exact restores passed
Failures counted as wins
```

## When To Use Smavg

Good first folders:

- old project versions
- repeated reports
- logs
- AI memory folders
- skill and runbook folders
- benchmark folders
- repeated notes

Poor first folders:

- random photos
- encrypted files
- zip files
- disk images
- one-off unique files

If Smavg cannot help much, it should say so.

## What Happens If You Apply Smavg

When you choose to archive a folder:

```bash
smavg apply ./my-folder --out my-folder.smavg
```

Smavg will:

1. make the archive
2. verify the archive
3. restore it to a temporary place
4. compare the restored files with the originals
5. report the result

Smavg does not delete your original folder automatically.

## What Happens For AI Agents

Instead of giving an AI agent a giant repeated folder, Smavg gives it a compact
map first:

```bash
smavg context ./my-folder --out context.md --json context.json
```

If exact detail matters, the agent asks Smavg for the exact file:

```bash
smavg expand-context context.json path/in/folder.txt --out exact-file.txt
```

The rule is:

```text
Map first. Exact file second. Verify always.
```

## The Trust Rule

Smavg only counts a result when the exact retrieval works.

```text
Exact restore or it does not count.
Failures counted as wins: 0.
```

Next: [QUICKSTART.md](QUICKSTART.md)
