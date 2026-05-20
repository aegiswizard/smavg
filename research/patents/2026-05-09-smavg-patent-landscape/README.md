# Smavg Patent & Prior-Art Landscape Research

**Date:** 2026-05-09  
**Project:** Smavg (Aegis Wizard / Roman Mataru)  
**Scope:** Technical research only. Not legal advice.  
**Researcher:** Kimi Code CLI  

## Executive Summary

This folder contains a patent and prior-art landscape study for Smavg, a local archive/filesystem storage engine that targets repeated/versioned information for byte-perfect storage reduction. The core concept—identify similar files, store stable patterns once, store only changes/residue, and restore every original byte-perfectly—sits in one of the most heavily patented and extensively researched areas in computer systems: data deduplication, delta compression, content-addressable storage, and backup/archive systems.

**The landscape is crowded.** Large incumbents (CommVault, Pure Storage, NetApp, Oracle, Western Digital, SAP) hold hundreds of granted patents covering block-level deduplication, content-defined chunking, tiered deduplication, feature-based deduplication, Rabin fingerprinting hardware, delta compression, and distributed deduplicated storage. Open-source systems (BorgBackup, Restic, Duplicacy, Git packfiles, Venti, LBFS, ZFS, bsdiff, xdelta, zstd) provide extensive non-patent prior art. Academic literature on content-defined chunking, log template compression, and binary differencing is decades deep.

**What this means for Smavg:**
- Many low-level building blocks (hashing, chunking, delta encoding, content-addressed stores) are well-documented prior art, but specific combinations implemented in recent enterprise patents may create proximity risks.
- Smavg’s potential differentiation—local-first, deterministic exact restore, category-specific reversible codecs, AI only for classification/similarity (not generation), archive-first before filesystem—should be documented, engineered, and described precisely in any future filings.
- **Any public release or patent filing requires attorney review.** This research does not conclude that Smavg is safe to ship.

## How to Read This Folder

| File | Purpose |
|------|---------|
| `patent_landscape.md` | Detailed patent landscape organized by category. Includes verified patent numbers, titles, assignees, dates, source URLs, summaries, and closeness ratings. |
| `patent_matrix.csv` | Machine-friendly matrix of the same patents for sorting/filtering. |
| `prior_art_and_systems.md` | Non-patent prior art: Git packfiles, rsync, Venti, LBFS, ZFS, BorgBackup, Restic, Duplicacy, bsdiff, xdelta, zstd dictionaries, log template methods, and more. |
| `smavg_risk_map.md` | Engineering risk map: high/medium/low closeness themes, design areas to study, and implementation ideas that need careful review. |
| `implementation_lessons.md` | Concrete technical lessons for what to build next, informed by the landscape. |
| `search_log.md` | Every search query used, sources searched, and notes on findings. |
| `sources.json` | Machine-readable list of all sources with URLs, types, and notes. |

## Biggest Technical Lessons for Smavg

1. **Chunking is a commodity.** Content-defined chunking (Buzhash, Rabin fingerprints) is extensively documented and implemented in open source. Do not claim novelty in chunking alone. Focus on *what you do with the chunks* and *how you select bases*.
2. **Delta compression is mature.** Git packfiles, bsdiff, xdelta/VCDIFF, and zstd dictionaries cover binary and semantic differencing. Smavg should study bsdiff’s bytewise-subtraction insight and Git’s delta-base selection heuristic.
3. **Exact restore is a strong differentiator.** Many systems prioritize compression ratio over deterministic reconstruction. Smavg’s commitment to byte-perfect, deterministic restore without AI generation is a genuine distinction—make it central to the architecture.
4. **AI-assisted similarity is an emerging patent hotspot.** Semantic/embedding-based deduplication is starting to appear in patent filings (e.g., Chinese application CN114818986A, Pure Storage feature-based dedup). If Smavg uses local embeddings *only* for candidate selection (not for lossy reconstruction), that boundary should be documented clearly.
5. **Log and structured-data template extraction is active research.** Drain, LogZip, LogReducer, LogShrink, and DeLog show that template-plus-variable encoding for logs is well-studied. Smavg can learn from parser-accuracy-vs-compression tradeoffs in this literature.
6. **Filesystem-level dedup is heavily patented.** CommVault’s tiered-dedup filesystem patents (e.g., US-9575673-B2 family) and Oracle’s ZFS dedup claims cover inline block-level dedup and pseudo-filesystem drivers. An archive-first approach (before a FUSE/overlay filesystem layer) may reduce proximity.

## Important Disclaimers

- **Not legal advice.** This is technical research for engineering awareness only.
- **Verified vs. unverified.** Where possible, patents are verified against Google Patents, USPTO PDFs, or EPO documents. Some patent numbers cited in the literature are noted but not fully verified.
- **No copying.** This research is intended to help Smavg design responsibly, not to copy patented methods.
- **Attorney review required.** Before public release or any patent filing, consult a qualified patent attorney.
