# Non-Patent Prior Art and Known Systems

**Research date:** 2026-05-09  
**Scope:** Open-source systems, academic papers, and publicly documented algorithms relevant to Smavg’s technical domain.  

---

## 1. Version Control & Delta Compression

### Git Packfiles
- **Source:** https://git-scm.com/docs/git-pack-objects/2.43.0
- **Papers:**  
  - "Principles of Dataset Versioning: Exploring the Recreation/Storage Tradeoff" (arXiv:1505.05211) — reverse-engineers Git’s delta algorithm: https://arxiv.org/pdf/1505.05211
  - "Effective Data Versioning for Collaborative Data Analytics" — further analysis of Git packfile heuristics: https://www.ideals.illinois.edu/items/112814/bitstreams/369753/data.pdf
- **What it does:** Git stores objects individually (loose objects), then periodically packs them into packfiles. Within a packfile, Git uses delta compression: it stores one version of a blob fully, then stores delta instructions for similar objects. Deltas can chain (default max depth 50). Git sorts objects by type, "name hash" (suffix-based grouping), and size before selecting delta bases.
- **Key technical details:**
  - Delta format: copy/insert instructions against a base object.
  - Base selection heuristic: sliding window of W=10 objects; chooses base minimizing `delta_size / (max_depth - depth_of_base)`.
  - Uses zlib (and increasingly zstd) for final compression.
  - Rabin-Karp-style fingerprinting in `diff-delta.c` for matching blocks.
- **What Smavg can learn:**
  - The "name hash" heuristic (grouping by filename suffix) is simple but effective for source code. Smavg could use content-type or path patterns for base-file candidate grouping.
  - Delta chain depth limits are critical for restore performance. Smavg should cap chain depth or use "snapshots" of full objects.
  - Packfile + index design is a proven pattern for content-addressed storage.

### Rsync Algorithm
- **Authors:** Andrew Tridgell and Paul Mackerras
- **Paper:** "The rsync algorithm," ANU Technical Report TR-CS-96-05, 1996
- **What it does:** Computes differences between remote files using a rolling checksum (Adler-32) and MD4 block hashes. The receiver sends hashes of fixed-size blocks; the sender matches against its version and sends literal data or block references.
- **What Smavg can learn:**
  - Rolling hashes enable efficient block-level diffing without transmitting entire files.
  - The two-level hash (fast rolling + strong hash) is a classic pattern for dedup/block-matching.
  - Fixed-size blocks fail on insertions; Smavg should use content-defined chunking instead.

---

## 2. Binary Differencing

### bsdiff
- **Author:** Colin Percival
- **Paper/Doc:** "Naive differences of executable code" (2003): http://www.daemonology.net/bsdiff/
- **What it does:** Computes binary diffs using suffix arrays (qsufsort) to find longest matches, then produces three streams: control (copy/insert instructions), diff (bytewise differences in matched regions), and extra (new data). The diff stream is mostly zeros when addresses shift uniformly, making it extraordinarily compressible with bzip2/zstd.
- **Key insight:** Bytewise subtraction of matched regions turns address shifts into low-entropy residue. A 58x compression ratio was demonstrated on FreeBSD security updates.
- **What Smavg can learn:**
  - If Smavg handles versioned binaries, bsdiff’s bytewise-subtraction approach is a gold standard.
  - Suffix-array construction is O(n log n) and memory-intensive; for very large files, streaming or chunked approaches may be needed.
  - The three-stream design (control + diff + extra) is a clean abstraction for deterministic reconstruction.

### xdelta / VCDIFF (RFC 3284)
- **Author:** Joshua P. MacDonald
- **Sources:**
  - xdelta 1.1.4 man page / README: https://manpages.debian.org/testing/xdelta/xdelta.1.en.html
  - VCDIFF RFC 3284 implementation: https://codeberg.org/pleonex/xdelta-sharp
- **What it does:** xdelta computes deltas between binary files using a fast linear algorithm based on the rsync algorithm. It uses zlib compression on the delta output. xdelta 3 implements VCDIFF (RFC 3284). Supports automatic gzip decompression/recompression.
- **What Smavg can learn:**
  - VCDIFF is a standardized delta format; using or supporting it could improve interoperability.
  - xdelta’s block-size parameterization matters for diff granularity.
  - MD5 integrity checks on patch application are a good practice for deterministic restore.

---

## 3. Content-Addressed Storage Systems

### Venti
- **Authors:** Sean Quinlan and Sean Dorward
- **Paper:** "Venti: a new approach to archival storage," FAST 2002: https://swtch.com/~rsc/papers/fndn/ (cited in Foundation paper)
- **What it does:** Venti is a write-once, read-many (WORM) content-addressed block storage server used in Plan 9. Blocks are addressed by SHA-1 hash. Fossil (Plan 9 file system) creates archival snapshots backed by Venti. Uses fixed-size blocking by default (with zero truncation), which limits dedup when insertions occur.
- **Source code / docs:**
  - Plan 9 venti man page: https://9fans.github.io/plan9port/man/man8/venti.html
  - Venti-streamchunk (variable-size chunking for Venti): https://github.com/stroucki/venti-streamchunk
- **What Smavg can learn:**
  - Content-addressed storage (CAS) is a foundational pattern; Venti is one of the earliest production CAS systems.
  - Fixed-size blocking fails for shifted data; variable-size chunking (Rabin) is essential for good dedup.
  - The index + data log + Bloom filter architecture is a proven design for CAS.

### Foundation (MIT PDOS)
- **Authors:** Russ Cox et al.
- **Paper:** "Fast, Inexpensive Content-Addressed Storage in Foundation" (2006-ish, referenced in pdos.csail.mit.edu publications): https://swtch.com/~rsc/papers/fndn/
- **What it does:** Foundation archives nightly disk snapshots using CAS, inspired by Venti but designed for consumer hardware (single USB disk). Uses a Bloom filter to detect new blocks quickly and achieves read/write speeds an order of magnitude higher than Venti on modest hardware.
- **What Smavg can learn:**
  - Bloom filters can speed up inline dedup by avoiding index lookups for likely-new blocks.
  - Consumer-grade CAS is feasible without RAID or high-speed disks.
  - Garbage collection (deleting snapshots and reclaiming unreferenced blocks) is analogous to log cleaning in LFS.

### LBFS (Low-Bandwidth Network File System)
- **Authors:** Athicha Muthitacharoen, Benjie Chen, David Mazières
- **Paper:** "A Low-Bandwidth Network File System," SOSP 2001: https://pdos.csail.mit.edu/papers/lbfs:sosp01/lbfs.pdf
- **What it does:** LBFS optimizes network file access by avoiding sending data already present on either client or server. It breaks files into variable-size chunks using a Rabin-like rolling hash, indexes chunks by SHA-1 hash, and transmits only missing chunks.
- **What Smavg can learn:**
  - Variable-size chunking with content-defined boundaries is essential for shift-resilient dedup.
  - SHA-1 (or similar) chunk indexing is standard practice.
  - The chunk size distribution matters: LBFS used average ~8KB chunks with min/max bounds.

---

## 4. Open-Source Backup / Archive Tools

### BorgBackup
- **Source:** https://borgbackup.readthedocs.io/en/stable/internals.html
- **What it does:** Deduplicating archiver with content-defined chunking (Buzhash), global dedup across all archives in a repository, authenticated encryption (AES-256-CTR + HMAC-SHA256 or AEAD), and multiple compression algorithms (LZ4, zstd, zlib, lzma).
- **Key technical details:**
  - Chunker: Buzhash rolling hash with variable chunk sizes.
  - Chunk ID: HMAC-SHA256 or Blake2b hash.
  - Repository format: append-only segments; manifest + archives + items + chunks.
  - FUSE mount for browsing archives.
- **What Smavg can learn:**
  - Buzhash is faster than Rabin for software chunking; consider it for Smavg’s chunker.
  - Global dedup across all archives is powerful for versioned file history.
  - Authenticated encryption should be considered early if Smavg stores sensitive data.
  - The segment compaction design is relevant for long-term archive maintenance.

### Restic
- **Sources:**
  - Restic design overview: https://restic.net/
  - DigitalOcean tutorial with technical details: https://www.digitalocean.com/community/tutorials/how-to-back-up-data-to-an-object-storage-service-with-the-restic-backup-client
- **What it does:** Backup tool written in Go. Content-defined chunking (Rabin fingerprinting), SHA-256 chunk IDs, AES-256-CTR + Poly1305-AES authenticated encryption, zstd compression (since v0.14). Supports many backends (S3, B2, Azure, GCS, SFTP, local).
- **Key technical details:**
  - Repository: encrypted chunks packed into "pack files"; JSON snapshot metadata referencing trees of content hashes.
  - Immutable snapshots; `forget` + `prune` for retention.
  - FUSE mount support.
- **What Smavg can learn:**
  - Restic’s repository format (pack files + index + JSON snapshots) is a clean, backend-agnostic design.
  - Content-defined chunking + global dedup is table stakes for modern backup tools.
  - Poly1305-AES authentication is a robust choice.

### Duplicacy
- **Source:** https://duplicacy.com/
- **What it does:** Cross-platform backup with a novel "lock-free deduplication" design. Multiple machines can back up to the same storage simultaneously without locks. Uses variable-size chunking and a two-step fossil collection algorithm for garbage collection without a centralized chunk database.
- **Key technical details:**
  - Lock-free dedup: relies on basic filesystem API; no repository locks.
  - Two-step fossil collection to safely delete unreferenced chunks.
  - RSA encryption option; erasure coding support.
- **What Smavg can learn:**
  - Lock-free designs simplify multi-writer scenarios, but Smavg is local-first so this may not apply immediately.
  - Fossil collection (mark-and-sweep garbage collection) is relevant for Smavg’s archive cleanup.
  - Pack-and-split chunking can cause slight dedup overhead; chunk boundary stability matters.

---

## 5. Filesystem-Level Deduplication

### ZFS Deduplication
- **Sources:**
  - Oracle ZFS Storage Appliance dedup overview: https://www.oracle.com/a/otn/docs/architectural-overview-oracle-zfs-storage-appliance.pdf
  - Jeff Bonwick’s blog post on ZFS dedup (archived): referenced in https://constantin.glez.de/posts/2010-03-16-opensolaris-zfs-deduplication-everything-you-need-to-know/
  - NetApp-Oracle ZFS patent litigation settlement: https://www.eweek.com/storage/netapp-oracle-settle-old-patent-litigation-over-zfs/
- **What it does:** Inline, block-level deduplication in the ZFS filesystem. A hash (usually SHA-256) is computed for each block; the Deduplication Table (DDT) tracks previously written blocks. Duplicate blocks are stored once with reference pointers.
- **What Smavg can learn:**
  - Inline dedup at the filesystem layer requires substantial RAM (DDT entries are ~320 bytes each).
  - The NetApp-Oracle litigation shows that filesystem dedup is a high-stakes patent area.
  - ZFS’s combination of dedup + LZ4 compression + snapshots is a benchmark for integrated storage reduction.

---

## 6. Compression Algorithms & Dictionary Methods

### Zstandard (zstd) & Dictionary Compression
- **Source:** https://github.com/facebook/zstd
- **What it does:** Fast lossless compression algorithm by Facebook/Meta (2016). Supports dictionary training for improved compression of small/repetitive payloads. Dual-licensed BSD/GPLv2.
- **Key technical details:**
  - Dictionary compression: train on sample corpus, then use dictionary for similar data.
  - Facebook used this for small JSON API responses and warehouse data.
  - Patent rights grant updated in 2017; no known patents on core algorithm.
  - Realtime Data LLC sued Facebook in 2018 alleging zstd infringed compression patents: https://news.bloomberglaw.com/ip-law/facebook-hit-with-patent-suit-over-data-compression-tech
- **What Smavg can learn:**
  - zstd dictionaries are highly relevant for Smavg’s template/variable extraction: a trained dictionary on stable patterns can improve compression of residue.
  - Dictionary training cost is non-trivial; amortize over large corpora.
  - Monitor Realtime Data LLC patent assertions if Smavg uses zstd in enterprise contexts.

---

## 7. Log & Structured-Data Template Compression

### Drain / LogPAI
- **Paper:** Pinjia He et al., "Drain: An Online Log Parsing Approach with Fixed Depth Tree," ICWS 2017: https://jiemingzhu.github.io/pub/pjhe_icws2017.pdf
- **Code:** https://github.com/logpai/Drain3
- **What it does:** Online log parser that extracts templates from raw log messages using a fixed-depth parse tree. Groups similar logs by token count and token similarity. Parameters are masked with `<*>`.
- **What Smavg can learn:**
  - Fixed-depth trees avoid unbalanced tree problems in streaming parsing.
  - Similarity thresholds and parameter masking rules are configurable.
  - Parser accuracy directly impacts downstream compression ratio (see DeLog paper).

### LogZip, LogReducer, LogShrink, DeLog
- **DeLog paper (2026):** "DeLog: An Efficient Log Compression Framework with Pattern Signature Synthesis," arXiv:2601.15084: https://arxiv.org/html/2601.15084v1
- **What they do:** Parser-based log compressors that separate static templates from dynamic variables, then apply dictionary encoding, delta encoding, and elastic encoding. DeLog identifies that existing methods fail on modern production logs due to complex templates and burst variables.
- **What Smavg can learn:**
  - Template extraction + variable encoding can achieve high compression on repetitive structured data.
  - Parser accuracy is the bottleneck: wrong templates destroy compression efficiency.
  - Modern logs violate old assumptions (e.g., same template = same length).
  - Smavg should consider whether its codecs are category-specific (logs vs. documents vs. binaries) rather than one-size-fits-all.

---

## 8. Academic Papers on Content-Defined Chunking & Deduplication

### "A comprehensive study of the past, present and future of data deduplication" (IEEE, 2016)
- **Authors:** W. Xia et al.
- **Cited in:** "Dynamic Prime Chunking Algorithm for Data Deduplication in Cloud Storage" (Korea Science): https://www.koreascience.or.kr/article/JAKO202120941688285.pdf
- **Summary:** Surveys chunking algorithms, dedup tradeoffs, and delta compression combinations.
- **What Smavg can learn:** Content-defined chunking (CDC) is well-studied; FastCDC and similar algorithms improve speed while maintaining dedup ratio.

### "Ddelta: A deduplication-inspired fast delta compression approach" (Performance Evaluation, 2014)
- **Authors:** W. Xia et al.
- **Cited in:** Same Korea Science survey above.
- **Summary:** Combines deduplication and delta compression for backup datasets.
- **What Smavg can learn:** Deduplication and delta compression are complementary; using both can outperform either alone.

---

## 9. Summary Table

| System | Domain | Key Technique | Relevance to Smavg |
|--------|--------|---------------|-------------------|
| Git packfiles | Version control | Delta compression + zlib/zstd | Delta encoding design; base selection heuristics |
| rsync | File sync | Rolling checksum + strong hash | Block matching; two-level hashing pattern |
| bsdiff | Binary patching | Suffix array + bytewise diff | Binary delta gold standard; residue compression |
| xdelta/VCDIFF | Binary diff | Rsync-based delta + zlib | Standardized delta format; integrity checks |
| Venti | Archival CAS | SHA-1-addressed blocks | CAS architecture; index + data log design |
| Foundation | Personal archival | CAS + Bloom filter | Consumer-grade CAS; snapshot deletion/GC |
| LBFS | Network filesystem | Variable-size chunking + SHA-1 | Content-defined chunking; shift resilience |
| BorgBackup | Backup archive | Buzhash CDC + global dedup + AEAD | Chunker choice; encryption; repository design |
| Restic | Backup archive | Rabin CDC + SHA-256 + Poly1305-AES | Repository format; pack files; backend agnosticism |
| Duplicacy | Backup archive | Lock-free dedup + fossil collection | GC without locks; multi-machine dedup |
| ZFS | Filesystem | Inline block dedup + DDT | Filesystem dedup is patented and RAM-hungry |
| zstd | General compression | Dictionary training | Template/residue compression; small-payload optimization |
| Drain/LogPAI | Log parsing | Fixed-depth tree template extraction | Template extraction for structured data |
| DeLog/LogZip | Log compression | Parser + dictionary/delta/elastic encoding | Category-specific codecs; parser accuracy matters |
