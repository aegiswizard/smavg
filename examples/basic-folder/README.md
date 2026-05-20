# Basic Folder Example

This example is for learning the basic Smavg flow.

Try:

```bash
smavg context examples/basic-folder --out /tmp/basic-context.md --json /tmp/basic-context.json
smavg apply examples/basic-folder --out /tmp/basic-folder.smavg
smavg verify /tmp/basic-folder.smavg
smavg restore /tmp/basic-folder.smavg /tmp/basic-folder-restored
```

Expected idea:

- Smavg scans the folder.
- Smavg creates a context map.
- Smavg creates an archive.
- Smavg restores exact files.

This folder is small, so it is for learning, not for headline benchmark claims.
