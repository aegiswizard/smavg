# Smavg Trust Wall v1

Date: 2026-05-20

## Result

Smavg now has a 100-test suite with 16 new adversarial trust-wall tests.

Verification commands run locally:

```bash
PYTHONPATH=src python3 -m unittest tests.test_trust_wall -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m compileall -q src tests
```

Measured result:

- Trust-wall tests: 16/16 passed.
- Full suite: 100/100 passed in 2.424 seconds.
- Compile check: passed.

## What The 16 Tests Cover

- Malicious container paths: absolute fallback path rejected.
- Malicious payload metadata: negative offset rejected.
- Header/payload integrity: header payload hash mismatch rejected.
- Extract safety: exact extraction refuses to overwrite existing output.
- Restore safety: symlink restore refuses to overwrite existing paths.
- Mixed restore fidelity: history text, binary, empty file, and executable mode restore byte-perfect.
- Context exactness: same-size source edits are caught by SHA-256.
- Context path safety: traversal requests are rejected.
- Receipt honesty: multiple exact expansions are counted without claiming full raw source was supplied.
- Ledger honesty: failed verification events remain visible but cannot inflate benefit totals.
- Safe-pack safety: archive-inside-source is refused and source remains in place.
- Daemon safety: one daemon cycle preserves the source tree fingerprint and performs no cleanup/delete.
- Service safety: launchd file generation writes a file but does not load/start anything.
- Plugin boundary: bundle declares Genesis license and wraps the Smavg core only.
- License consistency: public metadata points to `LICENSE`, not plain MIT text metadata.
- Weak-case honesty: low-repetition context reports `weak` without fake wins.

## Code Hardening From This Pass

- `ledger_report` now excludes failed verification events from benefit totals, category reductions, session totals, cleanup totals, and headline saved-token/disk counters.
- Failed events are still reported in `trust.failed_events`; they are just not counted as wins.
- The generated Smavg skill now explicitly states that it does not replace Smavg core verification and only calls the local core.

## Truth Boundary

These tests do not prove Smavg is production complete. They prove the current Python core preserves the trust rules covered above under local adversarial tests. Real benchmark claims still require real corpora, exact restore checks, and honest weak-case reporting.
