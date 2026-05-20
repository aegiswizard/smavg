# Smavg 🐲 Quick Start

This guide is for trying Smavg safely in five minutes.

## 1. Install Locally

From a downloaded zip:

```bash
unzip smavg.zip
cd smavg
python3 -m pip install -e .
```

From GitHub:

```bash
git clone https://github.com/aegiswizard/smavg.git
cd smavg
python3 -m pip install -e .
```

From an existing Smavg folder:

```bash
python3 -m pip install -e .
```

Check that the command works:

```bash
smavg --help
```

## 2. Scan First

Start with a read-only scan:

```bash
smavg scan
```

This looks for places where Smavg may help. It does not delete, move, or upload
anything.

If you are unsure, stop here and only read the report.

## 3. Read The Report

```bash
smavg report
```

Look for:

- useful folders
- weak folders
- estimated token savings
- estimated disk savings
- exact restore/verification notes

## 4. Check Status

```bash
smavg status
```

This shows:

- tokens saved today
- tokens saved all time
- disk saved all time
- exact expansion trust totals
- latest report path

## 5. Safely Archive A Folder

Only run this when you choose a folder yourself:

```bash
smavg apply ./my-folder --out my-folder.smavg
```

Smavg will:

1. create an archive
2. verify it
3. restore it to a temporary place
4. compare restored files against the source
5. report the result

Smavg does not delete the source.

The simplest rule:

```text
If verification does not pass, Smavg does not count it as a win.
```

## 6. Use Smavg For AI Context

Create a compact map:

```bash
smavg context ./my-folder --out context.md --json context.json
```

Give `context.md` to an AI agent first.

If the agent needs an exact file:

```bash
smavg expand-context context.json path/in/folder.txt --out exact-file.txt
```

This is how Smavg reduces repeated setup tokens without asking AI to invent
file contents.

## 7. Run Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -q
```

Expected result:

```text
Ran 100 tests
OK
```
