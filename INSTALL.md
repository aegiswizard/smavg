# Install Smavg

Smavg currently runs as a local Python command.

Requirements:

- Python 3.9 or newer
- macOS, Linux, or Windows
- no required runtime dependencies for the core

## Install From A Zip

If you downloaded `smavg.zip`:

```bash
unzip smavg.zip
cd smavg
python3 -m pip install -e .
```

Check the command:

```bash
smavg --help
```

## Install From GitHub

```bash
git clone https://github.com/aegiswizard/smavg.git
cd smavg
python3 -m pip install -e .
```

Check the command:

```bash
smavg --help
```

## First Safe Run

```bash
smavg scan
smavg report
smavg status
```

These commands are safe and read-only.

## Verify The Package

Developers can run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -q
PYTHONPATH=src python3 -m compileall -q src tests
```

Expected result:

```text
Ran 100 tests
OK
```

The release helper does the full local check:

```bash
scripts/verify-release.sh
```

## Optional AI Dependencies

The core works without extra AI packages.

Optional future/advanced packages are declared under extras:

```bash
python3 -m pip install -e ".[ai]"
```

Use the core first. Add optional packages only when a specific workflow needs
them.
