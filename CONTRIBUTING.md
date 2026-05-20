# Contributing To Smavg 🐲

Smavg welcomes useful improvements.

The standard is simple:

- no fake results
- no mock benchmark claims
- exact restore or it does not count
- weak cases must remain visible
- tests must match the risk of the change

## Local Setup

```bash
python3 -m pip install -e .
PYTHONPATH=src python3 -m unittest discover -s tests -q
```

## Before A Pull Request

Run:

```bash
scripts/verify-release.sh
```

## Good Contributions

- new verified codecs
- better docs
- safer restore checks
- stronger tests
- clearer reports
- better MCP/agent integration
- reproducible public benchmarks

## Bad Contributions

- hiding weak results
- counting failed runs as wins
- adding cloud dependencies to the core
- using AI regeneration for exact restore
- deleting user data automatically

## License

By contributing, you agree your contribution is provided under the Smavg
Modified MIT License, Version Genesis 1.0 2026.

See [CONTRIBUTOR_TERMS.md](CONTRIBUTOR_TERMS.md) for the plain-language
contributor terms.
