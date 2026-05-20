# Smavg Engineering Risk Map

**Research date:** 2026-05-09  
**Scope:** Practical engineering risks based on the patent and prior-art landscape. Not legal advice.  

---

## High-Closeness Patent Themes

These themes have granted patents that read closely on functionality Smavg may implement. Study carefully before shipping or filing.

### 1. Tiered / Pseudo-Filesystem Deduplication
- **Patents:** CommVault US 9,570,873 B2 family (US 10,474,638 B2, US 11,113,246 B2)
- **Theme:** A driver or filesystem layer that intercepts writes, offloads deduplicated data to secondary storage, and restores on read based on a dedup database.
- **Risk:** If Smavg builds a FUSE, overlay, or kernel module that presents a "smaller" filesystem by transparently deduplicating to a backing store, the claims may overlap.
- **Mitigation:** Stay archive-first. Expose archives as explicit read-only mounts (like Borg’s FUSE mount) rather than a transparent write-through dedup filesystem. Document the architectural separation: archive engine first, optional read-only FUSE viewer second.

### 2. Feature-Based / Embedding-Guided Deduplication
- **Patents:** Pure Storage US 10,789,211; Chinese application CN 114,818,986 A
- **Theme:** Using extracted features, embeddings, or similarity metrics to decide what to deduplicate or how to group data.
- **Risk:** If Smavg uses local embeddings to group similar files and then stores them relative to a shared base, patent examiners or competitors may argue similarity to feature-based dedup claims.
- **Mitigation:** Document that embeddings are used **only** for candidate selection (which base file to diff against), not for the deduplication decision itself. The actual dedup should remain byte-level (hashes) or delta-level (exact diffs). Keep the AI layer separable and optional.

### 3. Block-Signature Retention & Indexing for Protection Operations
- **Patents:** CommVault US 8,578,109 family
- **Theme:** Retaining block signatures (hashes) across backup/protection operations and using them for dedup.
- **Risk:** If Smavg maintains a persistent block/chunk hash index and uses it across multiple archive operations, the general concept is well-patented.
- **Mitigation:** Block/chunk hashing is fundamental prior art (Venti, LBFS, Git, Borg, Restic all predate or parallel these patents). Ensure your index structure and usage patterns are documented as implementations of known prior art. Do not copy CommVault’s specific retention/transaction schemes.

---

## Medium-Closeness Themes

These areas are active but Smavg’s current direction may be sufficiently distinct.

### 4. Inline Filesystem Block Deduplication
- **Patents:** Oracle ZFS dedup family (EP 3,566,130); NetApp WAFL-related assertions
- **Theme:** Inline block dedup inside a filesystem, with dedup tables in RAM/SSD.
- **Risk:** Medium because Smavg is currently archive-first, not a live filesystem. If Smavg later moves to a live write-time dedup filesystem, this risk escalates to High.
- **Mitigation:** Defer live filesystem dedup. If pursued later, use copy-on-write or log-structured designs with explicit versioning rather than transparent inline dedup.

### 5. Log / Structured-Data Template Compression
- **Patents:** CN 114,818,986 A (text similarity dedup); academic literature is extensive but patent filings are sparser in the West.
- **Theme:** Extracting templates and encoding variables for compression of semi-structured data.
- **Risk:** Medium. Parser-based log compression is well-published (Drain, LogZip, DeLog), but specific combinations of parser + encoder may be patentable.
- **Mitigation:** Use well-known parsing techniques (fixed-depth trees, LCS). Focus novelty on the reversible codec design, not the parser itself. Document that template extraction is prior art.

### 6. General Compression Acceleration Patents
- **Patents:** Realtime Data LLC family (US 9,054,728 B2, US 8,717,203 B2)
- **Theme:** Data compression systems with storage/retrieval acceleration.
- **Risk:** Medium if Smavg uses zstd or similar and markets it as "accelerated" or "optimized" storage. Realtime Data has asserted patents against Facebook.
- **Mitigation:** Use standard open-source compression (zstd, lz4) under their BSD/GPL licenses. Do not claim novelty in general compression. Monitor Realtime Data litigation if commercializing.

---

## Low/Background Themes

These are heavily prior-arted or distant from Smavg’s current direction.

### 7. Content-Defined Chunking (CDC)
- **Patents:** EP 3,051,699 B1 (Western Digital — hardware Rabin only)
- **Theme:** Software CDC using Rabin, Buzhash, FastCDC.
- **Risk:** Low. CDC is extensively documented in open literature and open source (Borg, Restic, LBFS). Hardware-specific patents do not cover software implementations.

### 8. Distributed / Cloud Deduplication
- **Patents:** CommVault US 9,633,033 B2; NetApp distributed dedup
- **Theme:** Multi-node dedup databases, failover, global dedup across clusters.
- **Risk:** Low. Smavg is local-first, single machine.

### 9. Backup Policy & Replication
- **Patents:** CommVault US 10,489,249; US 10,481,826
- **Theme:** Threshold-based backup triggering; dedup-aware replication.
- **Risk:** Low. Smavg is not a backup policy engine or replication system.

---

## Design Areas to Study Carefully

| Area | Why It Matters | Recommended Study |
|------|---------------|-------------------|
| **Delta base selection** | Git’s heuristic is well-published; improving it with embeddings is novel but borders on feature-based dedup patents. | Study Git pack-objects.c; document Smavg’s selection criteria independently. |
| **Deterministic restore** | Many systems prioritize ratio over exact reconstruction. Smavg’s exact-restore guarantee is a differentiator. | Ensure delta + template codecs are provably reversible; test with binary diff tools. |
| **Category-specific codecs** | Logs, source code, and binaries need different delta strategies. | Study bsdiff for binaries, Git deltas for source, Drain/DeLog for logs. |
| **Local embedding usage** | Using AI only for candidate selection reduces patent proximity. | Document the boundary: embeddings → candidate list; hashes/deltas → actual storage. |
| **Garbage collection** | Long-term archives need safe chunk deletion. | Study Duplicacy’s fossil collection and Borg’s segment compaction. |
| **FUSE / read-only mount** | If added, keep it strictly read-only and archive-backed. | Study Borg’s FUSE implementation; avoid write-through dedup filesystem semantics. |

---

## Implementation Ideas That Seem Broadly Prior-Arted / Common

These are generally safe to implement because they are extensively documented in open source and academic literature. Do not claim novelty in these areas alone.

- Content-defined chunking with Buzhash or Rabin fingerprints.
- SHA-256 or Blake2b chunk addressing.
- Delta compression using copy/insert instructions (VCDIFF-style).
- Content-addressed storage with an index + append-only data log.
- Compression with zstd, lz4, or zlib.
- Fixed-depth tree log parsing (Drain-style).
- Dictionary encoding of repetitive templates.

## Implementation Ideas That May Need Careful Review Before Public Release

These are not necessarily infringing, but they sit closer to recent patent claims. Document design decisions and prior-art influences carefully.

- **AI/embedding-guided base selection for delta compression.** Document that embeddings are only for candidate ranking, not for the storage decision.
- **Transparent write-through dedup filesystem layer.** High proximity to CommVault tiered-dedup patents. Prefer explicit archive + read-only mount.
- **Template extraction combined with learned dictionaries.** If Smavg trains dictionaries on extracted templates, document prior art in zstd dictionary compression and log template parsing.
- **Block-signature retention across incremental archives with transaction semantics.** Study CommVault’s family to ensure Smavg’s index design is independently conceived.

---

## Final Note

> **Requires attorney review.** This risk map is an engineering guide, not a freedom-to-operate opinion. Before public release, commercialization, or patent filing, engage a qualified patent attorney to review the specific implementation against the patents listed in `patent_landscape.md` and any continuations/divisionals filed since this research date.
