# Patent Landscape for Smavg

**Research date:** 2026-05-09  
**Scope:** Patents and published applications related to content-addressable storage, deduplication, delta compression, binary differencing, versioned-file storage, backup/archive systems, content-defined chunking, rolling-hash chunking, semantic/ML-assisted deduplication, filesystem-level dedupe, FUSE/overlay storage, template/variable extraction, log compression, and local-first archival.  
**Sources:** Google Patents, USPTO Patent Public Search, EPO/Espacenet, WIPO Patentscope, Justia Patents, academic papers, and verified patent PDFs.  

---

## 1. Content-Addressable Storage & Core Deduplication

### US 11,301,420 B2 — Highly Reusable Deduplication Database After Disaster Recovery
- **Assignee:** CommVault Systems, Inc.
- **Inventors:** Manoj Kumar Vijayan, Ganesh Haridas, Deepak Raghunath Attarde
- **Filed:** Jun. 29, 2016
- **Published (granted):** Apr. 12, 2022
- **Status:** Granted
- **Source:** https://patentimages.storage.googleapis.com/d2/ee/27/486e5c997fcd4d/US11301420.pdf
- **Summary:** A deduplication database is restored to a prior time; entries that do not correlate with archive file identifiers are pruned, enabling reuse after disaster recovery.
- **Why it matters to Smavg:** Covers deduplication metadata management and disaster recovery for dedup databases. Adjacent for Smavg if it plans to maintain dedup indices.
- **Claim themes:** Pruning dedup DB entries based on correlation with archive file identifiers; time-based recovery of dedup metadata.
- **Closeness:** Medium — metadata management is a common concern; specific pruning logic is narrow.

### US 9,633,033 B2 — High Availability Distributed Deduplicated Storage System
- **Assignee:** CommVault Systems, Inc.
- **Inventors:** Manoj Kumar Vijayan, Jaidev Oppath Kochunni, Saurabh Agrawal, Abhishek Narulkar
- **Filed:** Jan. 10, 2014
- **Published (granted):** Apr. 25, 2017
- **Status:** Granted
- **Source:** https://patentimages.storage.googleapis.com/bc/d9/08/108c45115c5bbd/US9633033.pdf
- **Summary:** Multiple deduplication database media agents store signatures of data blocks and act as failover agents if one becomes unavailable.
- **Why it matters to Smavg:** Distributed dedup signature databases. Smavg is local-first, so distributed failover is background reading.
- **Claim themes:** Distributed dedup DB agents; failover; block signatures in secondary storage.
- **Closeness:** Low/Background — Smavg is currently single-machine local.

### US 9,679,040 B1 — Performing Deduplication in a Distributed Filesystem
- **Assignee:** NetApp, Inc. (inferred from context; verify independently)
- **Filed:** (verify via USPTO)
- **Published (granted):** (verify via USPTO)
- **Status:** Granted
- **Source:** https://patentimages.storage.googleapis.com/d6/e0/d3/136dee39629330/US9679040.pdf
- **Summary:** Deduplication operations in a distributed filesystem environment.
- **Why it matters to Smavg:** General distributed filesystem dedup. Background only.
- **Closeness:** Low/Background

### US 8,548,944 — De-Duplication Based Backup of File Systems
- **Assignee:** (originally filed by applicant later acquired; referenced in IPR proceedings)
- **Filed:** Jul. 14, 2011
- **Published (granted):** Oct. 1, 2013
- **Status:** Granted (subject to past IPR)
- **Source:** https://ptacts.uspto.gov/ptacts/public-informations/petitions/1461094/download-documents?artifactId=k1DM0beBLt5RYtYjjUwF83Yit5JXYXB0903Qddn_lr_zgEoV6VX_njI
- **Summary:** Backup of file systems using deduplication techniques.
- **Why it matters to Smavg:** File-system-level dedup backup is close to Smavg’s archive-first use case.
- **Closeness:** Medium

---

## 2. Filesystem-Level & Tiered Deduplication

### US 9,570,873 B2 / US 10,474,638 B2 / US 11,113,246 B2 — Accessing a File System Using Tiered Deduplication
- **Assignee:** CommVault Systems, Inc.
- **Inventors:** Amit Mitkar, Paramasivam Kumarasamy, Rajiv Kottomtharayil
- **Filed:** Oct. 29, 2014 (priority)
- **Published (granted):** US 9,570,873 B2 (granted Feb 14, 2017); US 10,474,638 B2 (granted Sep 11, 2019); US 11,113,246 B2 (granted Sep 7, 2021)
- **Status:** Granted
- **Source (US 9,570,873 B2):** https://pubchem.ncbi.nlm.nih.gov/patent/US-9575673-B2
- **Source (US 11,113,246 B2):** https://pubchem.ncbi.nlm.nih.gov/patent/US-11113246-B2
- **Summary:** A pseudo-file-system driver intercepts read/write requests and offloads data to deduplicated secondary storage using a dedup database, presenting an "infinite" local filesystem.
- **Why it matters to Smavg:** This family covers exactly the filesystem-layer approach Smavg may eventually target. The claims include intercepting writes, offloading to dedup secondary storage, and restoring on read.
- **Claim themes:** Pseudo-filesystem driver; tiered dedup; infinite-capacity illusion; write interception and read restoration via dedup DB.
- **Closeness:** High — directly relevant if Smavg implements a FUSE/overlay or pseudo-filesystem layer.

---

## 3. Content-Defined Chunking & Rabin Fingerprints

### EP 3,051,699 B1 — Hardware Efficient Rabin Fingerprints
- **Assignee:** Western Digital Technologies, Inc.
- **Inventors:** Cyril Guyot, Dongyang Li, Qingbo Wang, Ken Yang
- **Filed:** Jan. 27, 2016 (EP); priority Jan. 29, 2015 (US provisional)
- **Published (granted):** Jun. 23, 2021
- **Status:** Granted
- **Source:** https://data.epo.org/publication-server/rest/v1.2/patents/EP3051699NWB1/document.pdf
- **Summary:** Hardware-efficient implementation of Rabin fingerprints for data deduplication.
- **Why it matters to Smavg:** Rabin fingerprints are a foundational technique for content-defined chunking. This patent covers hardware-efficient implementations, not the abstract algorithm itself.
- **Claim themes:** Hardware circuits for Rabin fingerprint computation; efficiency optimizations.
- **Closeness:** Low/Background — software-only Rabin chunking remains broadly prior-arted by academic literature and open source.

---

## 4. Feature-Based & Semantic Deduplication

### US 10,789,211 — Feature-Based Deduplication
- **Assignee:** Pure Storage, Inc.
- **Inventors:** Ethan L. Miller, Marco Sanvido
- **Published (granted):** Sep. 29, 2020
- **Status:** Granted
- **Source:** https://users.soe.ucsc.edu/~elm/cv.pdf (CV listing verified patent)
- **Summary:** Deduplication based on features extracted from data, rather than strict block-level identity.
- **Why it matters to Smavg:** "Feature-based" dedup is conceptually adjacent to semantic/similarity deduplication. If Smavg uses embeddings or structural features to group similar files, this patent family is relevant.
- **Claim themes:** Feature extraction; deduplication using features; storage device integration.
- **Closeness:** Medium — depends on how Smavg defines "features" vs. raw embeddings.

### US 10,761,759 — Deduplication of Data in a Storage Device
- **Assignee:** Pure Storage, Inc.
- **Inventors:** Ronald S. Karr, Ethan L. Miller
- **Published (granted):** Sep. 1, 2020
- **Status:** Granted
- **Source:** https://users.soe.ucsc.edu/~elm/cv.pdf
- **Summary:** Inline deduplication techniques in flash/SSD storage devices.
- **Closeness:** Low/Background — hardware-specific.

### CN 114,818,986 A — Text Similarity Calculation Deduplication Method and System
- **Assignee:** (Chinese applicant; verify via CNIPA)
- **Published:** 2022
- **Status:** Application
- **Source:** https://eureka.patsnap.com/patent-CN114818986A
- **Summary:** Uses a trained model to extract features from text, computes cosine similarity, and performs deduplication on hotline text data.
- **Why it matters to Smavg:** One of the few publicly accessible patent applications explicitly combining embeddings/similarity with deduplication. Shows the space is active.
- **Claim themes:** Model-based feature extraction; cosine similarity; top-K ranking; duplicate removal.
- **Closeness:** Medium — if Smavg uses embeddings for file similarity, proximity exists.

---

## 5. Data Compression Systems (General & Delta-Related)

### US 9,054,728 B2 — Data Compression Systems and Methods
- **Assignee:** Realtime Data, LLC
- **Inventor:** James J. Fallon
- **Filed:** Sep. 24, 2014
- **Published (granted):** Jun. 9, 2015
- **Status:** Granted
- **Source:** https://fedcircuitblog.com/wp-content/uploads/2022/03/21-2251-RealtimeArray-Appeal-Opening-Br-CORRECTED.pdf
- **Summary:** Data compression systems and methods; continuation of earlier applications in a large family.
- **Why it matters to Smavg:** Realtime Data LLC has asserted patents against Facebook/Zstandard. Their portfolio covers accelerated data storage and retrieval compression.
- **Claim themes:** Compression algorithms; data storage and retrieval acceleration.
- **Closeness:** Medium — general compression patent family with litigation history.

### US 8,717,203 B2 — Data Compression Systems and Methods
- **Assignee:** Realtime Data, LLC / James J. Fallon
- **Filed:** Sep. 24, 2013
- **Published (granted):** May 6, 2014
- **Status:** Granted
- **Source:** Same family document as above.
- **Summary:** Earlier grant in the same compression family.
- **Closeness:** Medium

### US 8,610,605 B2 — Method and System for Data Compression
- **Assignee:** SAP AG
- **Inventor:** Alexander Froemmgen
- **Filed:** Mar. 29, 2012
- **Published (granted):** Dec. 17, 2013
- **Status:** Granted
- **Source:** https://patentimages.storage.googleapis.com/fd/6c/16/70e87a89c45cd1/US8610605.pdf
- **Summary:** Method and system for data compression in enterprise systems.
- **Closeness:** Low/Background

---

## 6. Block-Level Backup, Signatures, & Replication

### US 8,578,109 / US 9,239,687 / US 9,639,289 — Systems and Methods for Retaining and Using Block Signatures in Data Protection Operations
- **Assignee:** CommVault Systems, Inc.
- **Inventors:** Manoj Kumar Vijayan et al.
- **Filed:** Dec. 30, 2010 (original)
- **Status:** Granted
- **Source:** https://pubchem.ncbi.nlm.nih.gov/patent/WO-2012044367-A1
- **Summary:** Retaining and using data block signatures (hashes) for data protection and deduplication.
- **Why it matters to Smavg:** Block-signature indexing is foundational to dedup. This family covers retaining signatures across protection operations.
- **Claim themes:** Block signatures; hash-based dedup; data protection operations.
- **Closeness:** Medium — block signatures are common, but specific retention/use claims may be narrow.

### US 10,489,249 — Dynamic Triggering of Block-Level Backups Based on Block Change Thresholds
- **Assignee:** CommVault Systems, Inc.
- **Inventors:** Bangalore Prashanth Nagabhushana et al.
- **Filed:** Sep. 20, 2016
- **Published (granted):** Nov. 19, 2019
- **Status:** Granted
- **Source:** https://www.storagenewsletter.com/2019/12/23/commvault-assigned-twenty-two-patents/
- **Summary:** Monitors block changes, triggers block-level backups when thresholds are crossed, and maintains historical change data.
- **Closeness:** Low/Background — backup policy logic.

### US 10,481,826 — Replication Using Deduplicated Secondary Copy Data
- **Assignee:** CommVault Systems, Inc.
- **Inventors:** Manoj Kumar Vijayan, Joe Sabu Thyvelikkakath Job
- **Filed:** Sep. 30, 2016
- **Published (granted):** Nov. 19, 2019
- **Status:** Granted
- **Source:** https://www.storagenewsletter.com/2019/12/23/commvault-assigned-twenty-two-patents/
- **Summary:** Uses deduplicated secondary copies for replication, reducing impact on production machines.
- **Closeness:** Low/Background — replication focus.

---

## 7. ZFS / Block-Level Inline Deduplication

### EP 3,566,130 — ZFS Block-Level Cloud Deduplication (European Validation)
- **Assignee:** Oracle International Corporation
- **Published (validated):** Dec. 13, 2023
- **Status:** Granted (European validation)
- **Source:** https://economie.fgov.be/sites/default/files/Files/Intellectual-property/Recueil%20brevets/recueil-brevets-2024-15.pdf
- **Summary:** Cloud-scale ZFS block-level deduplication.
- **Why it matters to Smavg:** Oracle’s ZFS dedup patents (and NetApp litigation history) show that block-level inline dedup in filesystems is heavily patented.
- **Closeness:** Medium — filesystem inline dedup is crowded; archive-first approaches may sidestep.

---

## 8. Log & Structured-Data Template Compression

*Note:* Patent filings specifically on log template compression (Drain-style parsing plus encoding) are less visible in Western patent databases than in academic literature. The following application was located:

### CN 114,818,986 A — Text Similarity Calculation Deduplication (also listed under Semantic)
- **Relevance:** Uses model-based feature extraction for dedup of structured/semi-structured text (hotline logs). Demonstrates that ML + similarity + dedup is being patented in text/log domains.
- **Closeness:** Medium

*Additional note:* Academic non-patent prior art (Drain, LogZip, LogReducer, LogShrink, DeLog) is extensive; see `prior_art_and_systems.md`.

---

## 9. Patents Referenced in Literature but Not Fully Verified

The following patent numbers appear frequently in deduplication literature and patent citations. They are listed here for awareness but were not independently verified during this research. Treat as pointers for future attorney-led searches.

| Patent Number | Context in Literature | Source |
|---------------|----------------------|--------|
| US 6,152,966 | Cited in academic papers related to content-addressable / Rabin fingerprinting | https://bibliotekanauki.pl/articles/410499.pdf |
| US 5,854,856 | Content-based video compression (template + motion data) | https://users.ece.cmu.edu/~moura/patents/jasinschi/United%20States%20Patent%205,854,856-test.htm |
| US 5,533,051 | "Method for Data Compression" (controversial; claimed compressing random data) | http://gailly.net/05533051.html |
| US 6,204,375 | Cited in patent reference lists | https://lucris.lub.lu.se/ws/portalfiles/portal/46061742/thesis_for_publisering.pdf |
| US 6,031,878 | Cited in patent reference lists | https://lucris.lub.lu.se/ws/portalfiles/portal/46061742/thesis_for_publisering.pdf |
| US 6,032,411 | Cited in patent reference lists | https://lucris.lub.lu.se/ws/portalfiles/portal/46061742/thesis_for_publisering.pdf |
| US 6,038,234 | Cited in patent reference lists | https://lucris.lub.lu.se/ws/portalfiles/portal/46061742/thesis_for_publisering.pdf |
| US 6,603,4059? | Cited in patent reference lists (possibly US 6,034,059) | https://lucris.lub.lu.se/ws/portalfiles/portal/46061742/thesis_for_publisering.pdf |
| US 6,584,140 | Cited in patent reference lists | https://core.ac.uk/download/pdf/14693388.pdf |
| US 7,117,454 | Cited in patent reference lists | https://data.epo.org/publication-server/rest/v1.2/patents/EP2792662NWA1/document.pdf |
| US 7,014,866 | Cited in patent reference lists | https://data.epo.org/publication-server/rest/v1.2/patents/EP2792662NWA1/document.pdf |
| US 8,307,177 | CommVault virtualization data management | Referenced in US 9,633,033 |
| US 8,285,681 | CommVault cloud storage dedup | Referenced in US 9,633,033 |
| US 7,035,880 | CommVault modular backup/retrieval | Referenced in US 9,633,033 |
| US 7,343,453 | CommVault hierarchical storage info | Referenced in US 9,633,033 |
| US 7,395,282 | CommVault hierarchical backup | Referenced in US 9,633,033 |
| US 7,246,207 | CommVault dynamic storage operations | Referenced in US 9,633,033 |
| US 10,248,657 | CommVault data object store for cloud | Referenced in CommVault lawsuit coverage |
| US 10,210,048 | CommVault selective snapshot/backup VMs | Referenced in CommVault lawsuit coverage |
| US 9,740,723 | CommVault virtualization data management | Referenced in CommVault lawsuit coverage |
| US 8,762,335 | CommVault storage operation access security | Referenced in CommVault lawsuit coverage |
| US 7,840,533 | CommVault image-level snapshot | Referenced in CommVault lawsuit coverage |
| US 7,725,671 | CommVault redundant metadata access | Referenced in CommVault lawsuit coverage |
| US 8,447,728 | CommVault storage operation access security | Referenced in CommVault lawsuit coverage |

---

## Summary by Closeness

| Closeness | Count | Themes |
|-----------|-------|--------|
| High | 1–2 | Tiered filesystem dedup (CommVault family) if Smavg builds a filesystem layer. |
| Medium | 8–10 | Feature-based dedup, semantic similarity dedup, block-signature systems, general compression families, ZFS inline dedup, file-system backup dedup. |
| Low/Background | 15+ | Distributed dedup, hardware Rabin, replication, backup policy triggering, hardware-specific dedup, enterprise compression. |

*Counts are approximate because closeness depends on Smavg’s exact implementation choices.*
