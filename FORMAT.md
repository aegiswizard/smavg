# Smavg Container Format v1

This document specifies the single-file `.smavg` archive written by Container
v1. The format is designed for deterministic, byte-perfect restore. AI may help
choose a storage plan before writing the archive, but archive reading never
uses AI and never approximates bytes.

## File Layout

```text
+---------------------------+
| fixed header              |
+---------------------------+
| compressed JSON manifest  |
+---------------------------+
| payload region            |
+---------------------------+
```

All multi-byte integers in the fixed header are little-endian unsigned 64-bit
values.

## Fixed Header

The fixed header is 88 bytes:

| Offset | Size | Field | Description |
| ---: | ---: | --- | --- |
| 0 | 8 | magic | ASCII `SMAVG001` |
| 8 | 8 | manifest_length | compressed manifest byte length |
| 16 | 8 | payload_length | payload region byte length |
| 24 | 32 | manifest_sha256 | SHA-256 of the compressed manifest bytes |
| 56 | 32 | payload_sha256 | SHA-256 of the payload region bytes |

The total file size must equal:

```text
88 + manifest_length + payload_length
```

If the size does not match, readers must reject the archive.

## Manifest

The manifest is UTF-8 JSON compressed with zlib. It is intentionally
self-describing and versioned.

Required top-level fields:

| Field | Type | Description |
| --- | --- | --- |
| `format` | string | Must be `smavg-container` |
| `version` | integer | Must be `1` |
| `created_at` | string | UTC ISO timestamp |
| `source_path` | string | Original local source path, informational only |
| `file_count` | integer | Number of files restored from the archive |
| `logical_bytes` | integer | Sum of restored file byte lengths |
| `payload_bytes` | integer | Payload region byte length |
| `payload_sha256` | string | SHA-256 hex digest of payload region |
| `manifest_codec` | string | Must be `zlib` for v1 |
| `families` | array | Structural family records |
| `fallback_files` | array | Per-file fallback records |
| `planner` | object/null | Human-readable planner report |

Container v1 writers also emit these tree-metadata fields. Readers accept
archives without them for compatibility with early v1 test archives, but when
`tree_entries` is present the tree fields must validate.

| Field | Type | Description |
| --- | --- | --- |
| `tree_entries` | array | Directory and symlink records restored alongside regular files |
| `tree_entry_count` | integer | Number of `tree_entries` records |
| `file_mode_default` | integer | Default permission bits for regular files, omitted if there are no files |
| `file_mode_overrides` | object | Map of relative file paths to permission bits when they differ from the default |
| `metadata_scope` | object | Declares which filesystem metadata v1 does and does not preserve |

`payload_bytes` and `payload_sha256` duplicate the header values in readable
form. Readers must treat the header as authoritative for locating the payload
and must verify both header hashes before trusting the manifest.

## Payload Region

The payload region is a byte string containing concatenated records. Each
manifest record stores an `offset` and `length` into this region.

Offsets are zero-based relative to the start of the payload region. Readers
must reject negative offsets, negative lengths, or ranges outside the payload
region.

## Memory Contract

Container v1.1 readers must not load the full `.smavg` archive into memory.
The expected memory shape is:

```text
O(compressed manifest + largest active payload segment)
```

The reader must:

- read only the fixed header first
- read only the compressed manifest before payload access
- verify the payload-region SHA-256 by streaming the payload region in chunks
- seek to individual payload records by manifest offset and length
- stream `full_zlib` fallback records during verify and restore
- write fallback restore bytes directly to a temporary file before atomically
  moving it into place

Current exception: legacy `history_pack_v2_lzma` is still a whole-family
payload. A reader may load one active v2 history-pack segment to decode it, but
must not load the entire archive. `history_pack_v3_chunked_lzma` and
`history_pack_v4_merkle_lzma` history packs are checkpointed into independently
compressed chunks and should be verified, restored, and extracted one active
chunk at a time.

Writers should also avoid building the full payload region in memory. Container
v1.1 writers spool payload bytes to a temporary payload file, then atomically
assemble the final archive after the compressed manifest is known.

## Family Records

Container v1 supports one structural family kind:

```json
{
  "id": "family-0",
  "kind": "history_pack",
  "label": "whole-corpus-history",
  "codec": "history_pack_v4_merkle_lzma",
  "offset": 0,
  "length": 276201,
  "sha256": "hex...",
  "file_count": 1547,
  "logical_bytes": 171156036,
  "fallback_payload_bytes": 34477268,
  "reason": "all files matched detected history families; single whole-corpus pack was smallest",
  "sample_paths": ["path/example"]
}
```

Required fields:

| Field | Type | Description |
| --- | --- | --- |
| `id` | string | Stable identifier within this archive |
| `kind` | string | Must be `history_pack` in v1 |
| `codec` | string | Must be `history_pack_v2_lzma`, `history_pack_v3_chunked_lzma`, or `history_pack_v4_merkle_lzma` in v1 |
| `offset` | integer | Payload region offset |
| `length` | integer | Payload segment length |
| `sha256` | string | SHA-256 hex digest of this payload segment |
| `file_count` | integer | Number of files produced by this family |
| `logical_bytes` | integer | Sum of file bytes produced by this family |

The `label`, `fallback_payload_bytes`, `reason`, and `sample_paths` fields are
informational for reports.

The legacy `history_pack_v2_lzma` payload is an LZMA-compressed JSON document.
That inner payload carries each member path, byte length, and SHA-256 hash.
Readers must decode it deterministically and verify the member count and
logical byte total against the family record.

The `history_pack_v3_chunked_lzma` payload has this inner layout:

```text
+-------------------------------+
| v3 fixed header                |
+-------------------------------+
| zlib-compressed JSON index     |
+-------------------------------+
| concatenated LZMA chunks       |
+-------------------------------+
```

The v3 fixed header stores magic `SMHSTV3\n`, compressed index length, chunk
region length, and SHA-256 of the compressed index. The v3 index stores the
checkpoint interval, family/group summaries, and chunk records. Each chunk
record stores an offset, length, SHA-256, member path list, file count, and
logical byte total. Each chunk payload is an LZMA-compressed JSON document that
stores one checkpoint base plus line deltas until the next checkpoint. Member
SHA-256 and byte-size checks live inside the chunk entries themselves.

V3 readers must verify the v3 header, index hash, chunk range, chunk hash,
member path order, member byte length, member SHA-256, chunk file count, and
chunk logical byte total. Random single-file extraction may read only the chunk
whose index member list contains the requested path.

The `history_pack_v4_merkle_lzma` payload has the same outer layout as v3, but
uses fixed-header magic `SMHSTV4\n` and an index with `version: 4` and
`verification: "chunk-merkle-root"`.

V4 removes repeated per-member path, byte length, and SHA-256 fields from the
compressed delta entries. The v4 index stores member path order and group order
for each chunk. Each LZMA chunk stores only compact entries:

```json
{
  "v": 4,
  "chunk_index": 0,
  "entries": [
    ["b", "base-bytes-as-latin1"],
    ["d", [["=", 0, 12], ["+", "inserted-bytes-as-latin1"]]]
  ]
}
```

Entry kind `b` is a checkpoint/base byte string. Entry kind `d` is a line delta
against the previous restored member in the same group.

Each v4 chunk index record adds:

| Field | Type | Description |
| --- | --- | --- |
| `root` | string | SHA-256 hex root over restored `(path, size, sha256(bytes))` records in chunk order |
| `members` | array | Relative restored paths in chunk order |
| `groups` | array | History group names in chunk order, same length as `members` |

V4 readers must verify the v4 header, index hash, chunk range, chunk hash,
member path order, group list length, chunk file count, chunk logical byte
total, and final chunk root. Random single-file extraction still decodes and
validates the containing chunk before returning the requested file.

## Fallback File Records

Fallback records store files that did not belong to a winning structural
family.

```json
{
  "path": "unrelated/README.md",
  "codec": "full_zlib",
  "offset": 123775,
  "length": 3266,
  "payload_sha256": "hex...",
  "sha256": "hex...",
  "logical_size": 8763,
  "is_text": true
}
```

Required fields:

| Field | Type | Description |
| --- | --- | --- |
| `path` | string | POSIX relative restore path |
| `codec` | string | Must be `full_zlib` in v1 |
| `offset` | integer | Payload region offset |
| `length` | integer | Payload segment length |
| `payload_sha256` | string | SHA-256 hex digest of compressed segment |
| `sha256` | string | SHA-256 hex digest of restored file bytes |
| `logical_size` | integer | Restored byte length |
| `is_text` | boolean | Informational only |

Paths must be relative POSIX paths. Readers must reject empty paths, absolute
paths, `..`, paths beginning with `../`, and paths containing `/../`.

## Tree Metadata

Tree metadata records filesystem structure that is not represented by regular
file payloads.

Directory record:

```json
{
  "path": "nested/empty",
  "kind": "dir",
  "mode": 493
}
```

Symlink record:

```json
{
  "path": "latest-report",
  "kind": "symlink",
  "target": "reports/report-v12.md"
}
```

Rules:

- `path` is a safe relative POSIX path and follows the same safety rules as
  fallback file paths.
- `kind` must be `dir` or `symlink` in Container v1.
- Directory `mode` is an integer permission mask from `0` to `0o7777`.
- Symlink `target` is stored as link target text and must not contain a null
  byte. Readers must restore the symlink itself and must not follow the target
  while archiving.
- Regular-file bytes are represented by family and fallback records. Regular
  file permission bits are represented compactly by `file_mode_default` plus
  `file_mode_overrides`.
- `tree_entry_count` must equal the number of records in `tree_entries`.

Container v1 metadata scope:

| Metadata | Preserved |
| --- | --- |
| Regular-file bytes | yes |
| Relative paths | yes |
| Directories | yes |
| Empty directories | yes |
| File permission modes | yes |
| Directory permission modes | yes |
| Symlinks | yes, as symlinks |
| Timestamps | no |
| Ownership | no |
| Hard-link identity | no |

## Restore Rules

A reader must:

1. Verify fixed header magic and total size.
2. Verify compressed manifest SHA-256.
3. Verify payload region SHA-256.
4. Decode the zlib-compressed JSON manifest.
5. Validate supported `format`, `version`, and `manifest_codec`.
6. For each family record:
   - Validate payload range.
   - Verify family payload SHA-256.
   - Decode using the declared codec.
   - Verify produced file count and logical byte total.
   - Reject duplicate restored paths.
7. For each fallback record:
   - Validate payload range.
   - Verify compressed payload SHA-256.
   - Decode using `full_zlib`.
   - Verify restored file size and SHA-256.
   - Reject duplicate restored paths.
8. Validate tree metadata, if present:
   - Verify `tree_entry_count`.
   - Validate all tree paths.
   - Reject duplicate tree paths.
   - Reject unknown tree kinds.
   - Validate permission-mode ranges.
9. Verify top-level restored file count and logical byte total.
10. Restore directories before regular files.
11. Restore symlinks after regular files without following targets.
12. Apply regular-file modes and directory modes.

Any failed check must reject the archive. Partial restore from a failed archive
is not part of Container v1.

## Current Limitations

- Container v1 is not an appendable format and has no cross-archive family
  index yet.
- Container v1 has no forward error correction or parity blocks.
- Container v1 does not preserve timestamps, ownership, ACLs, extended
  attributes, or hard-link identity.
- `history_pack_v2_lzma`, `history_pack_v3_chunked_lzma`,
  `history_pack_v4_merkle_lzma`, and `full_zlib` payload codecs are specified.

These are explicit future format extensions, not hidden behavior.
