# Implementation Lessons for Smavg

**Research date:** 2026-05-09  
**Scope:** Concrete technical lessons drawn from the patent and prior-art landscape, focused on what Smavg should build next.  

---

## 1. Better Chunking

**Lesson:** Do not reinvent chunking for novelty. Chunking is a commodity. Focus on chunking that serves the rest of the pipeline.

- **Use Buzhash or FastCDC for speed.** BorgBackup uses Buzhash; Restic uses Rabin. Benchmark both. FastCDC (published in academic literature) offers near-Rabin dedup ratios at higher speeds.
- **Bound chunk sizes.** LBFS used min 2KB / max 64KB with average ~8KB. Unbounded chunk sizes cause memory and indexing problems.
- **Make chunking seedable.** If Smavg wants deterministic archives, the chunking parameters (polynomial, mask, min/max sizes) should be part of the archive configuration so the same input always produces the same chunk stream.
- **Consider super-chunks for indexing.** Storing chunks in larger packfiles (like Git packfiles or Restic packs) reduces metadata overhead and improves sequential read performance.

---

## 2. Smarter Base Selection

**Lesson:** The biggest compression wins in versioned data come from choosing the right base file for delta encoding. Git’s heuristic is simple and effective; Smavg can do better with domain awareness.

- **Adopt Git’s delta window heuristic as a baseline.** Sort candidates by type, path suffix, and size. Maintain a sliding window of recent candidates. Score bases by `delta_size / depth_penalty`.
- **Add content-similarity pre-filtering.** Use a fast perceptual hash (e.g., ssdeep, tlsh) or local embedding to rank the top-N most similar candidates before running the expensive delta trial. This is where AI adds value without touching the storage layer.
- **Cap delta chain depth.** Git defaults to max depth 50. For archives, consider lower depth (20–30) with periodic "snapshot" full objects to guarantee fast random restore.
- **Store reverse deltas for some use cases.** If the latest version is accessed most often, store the latest full and older versions as reverse deltas. Git uses forward deltas (old → new) for packfile efficiency; choose based on access pattern.

---

## 3. Packfile / Index Design

**Lesson:** A good repository format is append-only, self-describing, and easy to verify. Study Git and Restic.

- **Packfiles + separate index.** Git stores objects in `.pack` files with a `.idx` index. Restic uses encrypted pack files and a JSON index. Both allow fast random access.
- **Content-addressed index entries.** Index keys should be strong hashes (SHA-256 or Blake3) of chunk content. Values should be (packfile_id, offset, length).
- **Manifest/snapshot file.** Each archive version should have a top-level manifest listing all files, their chunk hashes, and metadata. This makes restore trivial and enables fast pruning.
- **Append-only with compaction.** Writes should append to the current packfile. Background compaction (like Borg’s segment compaction) can rewrite fragmented packfiles and reclaim space after pruning.

---

## 4. Log Template Compression

**Lesson:** Log compression is not just about general-purpose algorithms. Template extraction plus variable encoding can beat gzip/lzma by 2–5x on repetitive logs.

- **Use a parser, but keep it simple.** Drain’s fixed-depth tree is proven, fast, and online. Integrate or port Drain3 logic for log ingestion.
- **Separate template store from variable store.** Store each unique template once with an ID. Store each log line as `(template_id, [variables...], timestamp_delta)`. This is what LogZip and DeLog do.
- **Encode variables intelligently.**
  - Timestamps: delta encoding from previous line.
  - Integers: elastic encoding (variable-length with stop bits).
  - Strings: dictionary encoding for repeated values (IP addresses, user IDs).
- **Measure parser accuracy.** DeLog shows that parser errors directly degrade compression. Add a validation pass: if a parsed line cannot be reconstructed byte-perfectly, fall back to storing the raw line.
- **Category-specific codecs.** Do not use the same codec for logs, JSON configs, source code, and binaries. Detect content type and switch codecs.

---

## 5. Structured-Data Codecs

**Lesson:** Semi-structured data (JSON, CSV, XML, protobuf) often has stable schema and volatile values. Treat it like logs.

- **Schema extraction.** For JSON/CSV, extract a stable schema (keys, column order) as a template. Store values in columnar order.
- **Columnar delta encoding.** If versions of a JSON config differ only in a few values, store the base config once and per-version columnar deltas.
- **Key normalization.** Sort JSON keys deterministically so that semantically identical objects have identical byte representations before hashing.

---

## 6. Local Embeddings as Candidate Selectors Only

**Lesson:** The patent landscape around AI-assisted deduplication is warming up. Keep AI on the "search" side, not the "storage" side.

- **Embedding pipeline:** Compute a lightweight local embedding (e.g., sentence-transformers for text, perceptual hashes for images) for each incoming file.
- **Candidate index:** Maintain an approximate-nearest-neighbor index (HNSW, faiss, or even brute-force for local archives) mapping embeddings to file IDs.
- **Delta trial:** For a new file, query the ANN index for top-K candidates. Run actual delta compression against each candidate. Choose the smallest delta.
- **Storage decision:** The stored form is still either (a) full chunk hash references (dedup) or (b) delta instructions against a base (delta compression). The embedding never affects the stored bytes.
- **Documentation:** Write this boundary clearly in design docs. It helps both engineering clarity and any future patent positioning.

---

## 7. Byte-Perfect Deterministic Restore

**Lesson:** Many systems accept approximate restore (e.g., gzip recompression may differ). Smavg’s exact-restore guarantee is a genuine differentiator—engineer it from day one.

- **Reversible codecs only.** Every codec must have a provable inverse. Test with property-based testing: `restore(archive(file)) == file` for all inputs.
- **No lossy AI generation.** Never use generative AI to reconstruct file content. AI may be used for classification, similarity, or compression parameter selection only.
- **Checksum verification.** Store a strong hash (Blake3 or SHA-256) of the original file in the manifest. Verify on restore.
- **Deterministic chunking + deterministic delta.** Given the same archive configuration and the same input history, the archive bytes should be identical. This enables reproducibility and dedup across independent archive runs.

---

## 8. Avoiding Unsafe AI Regeneration

**Lesson:** The current AI hype creates pressure to use generative models for "smart compression." This is legally risky and technically unsound for archival.

- **Do not use LLMs to regenerate files.** Even if an LLM can reconstruct a document from a prompt, the output is not byte-perfect and may introduce hallucinations.
- **Do not use diffusion models for image reconstruction.** Same problem: non-deterministic, lossy, and legally murky.
- **Safe AI uses for Smavg:**
  - Content-type classification (text vs. binary vs. image vs. log).
  - Similarity scoring for base selection.
  - Anomaly detection (flagging files that compress unusually poorly).
  - Parameter tuning (suggesting chunk sizes or compression levels based on content type).

---

## 9. Recommended Build Order

Based on the landscape, here is a pragmatic build order for Smavg:

1. **Core CAS layer:** Append-only packfiles, content-addressed chunk index, manifest/snapshot files. (Prior art: Venti, Git, Restic)
2. **Content-defined chunker:** Buzhash or FastCDC with configurable min/max sizes. (Prior art: Borg, LBFS)
3. **Delta compressor:** VCDIFF-style or bsdiff-inspired engine with copy/insert/diff instructions. (Prior art: Git, xdelta, bsdiff)
4. **Base selection heuristic:** Git-style window + optional embedding pre-filter. (Prior art: Git pack-objects)
5. **Category detection + codec switcher:** File-type detection → chunker/delta/codec selection. (Novel for Smavg if done well)
6. **Log/structured-data codec:** Drain-style parser + template/variable encoding. (Prior art: LogZip, DeLog)
7. **Archive FUSE mount:** Read-only mount of any snapshot. (Prior art: Borg, Restic)
8. **Compaction / pruning:** Fossil collection or segment compaction for garbage collection. (Prior art: Duplicacy, Borg)

---

## 10. Metrics to Track

- **Deduplication ratio:** unique bytes / total bytes (target: 5–15x for versioned source/logs)
- **Delta compression ratio:** delta size / full size (target: <10% for small version changes)
- **Restore throughput:** MB/s for random file restore from archive
- **Parser accuracy:** % of log lines reconstructing byte-perfectly (target: >99.9%)
- **Embedding recall:** % of optimal delta bases found in top-K candidates
- **Index memory:** bytes of RAM per million chunks
