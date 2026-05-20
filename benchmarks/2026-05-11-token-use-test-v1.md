# Smavg Token Use Test v1

Date: 2026-05-11

Question tested:

Can Smavg reduce token usage for repetitive web-agent work where the target
website changes, but the workflow instructions, safety rules, runbooks,
handoffs, and preferences are mostly the same?

## Target And Jobs

Target website: Hacker News.

Jobs:

1. Front/news page scan: `https://news.ycombinator.com/news`
2. Newest page scan: `https://news.ycombinator.com/newest`
3. Show HN page scan: `https://news.ycombinator.com/show`

No public actions were performed. The pages were fetched live from Hacker News
and saved as raw HTML under:

`/Users/mac/.codex/smavg-private-benchmarks/2026-05-11-token-use-test-v1/`

BrowserMCP transport was unavailable during this run, so the live target-page
portion was measured from fetched real HN HTML rather than BrowserMCP
snapshots. This is still useful for token accounting: live page content is
common to both paths, while Smavg targets the repeated workflow setup.

## Method

Without Smavg:

- The agent receives the full Hacker News workflow corpus for each job.
- Corpus: Codex HN skill, Kimi HN skill, HN workflow memory, shared workflow
  runbook, current focus, session handoff, and collaboration preferences.

With Smavg:

- The agent receives the HN workflow context brief.
- It expands only the two exact files needed for operation:
  `skills/codex/hackernews-browsermcp/SKILL.md` and
  `memories/medium-term/hackernews_browsermcp_workflow.md`.
- Exact expansion was verified with SHA-256 and `cmp -s`.

Token counts use Smavg's deterministic `estimate_tokens` function. They are
estimates, but they are computed the same way for both sides.

## Live Page Evidence

Fetched real HN pages:

| Job | HTML bytes | HTML tokens | Sample top titles |
| --- | ---: | ---: | --- |
| News | 35,186 | 14,534 | `Hardware Attestation as Monopoly Enabler`; `Local AI needs to be the norm`; `The Greatest Shot in Television: James Burke Had One Chance to Nail This Scene (2024)` |
| Newest | 40,908 | 16,476 | `Semantic Phonons: Lattice Vibrations in AI Internals`; `Stocker - AI stock prediction with ML ensemble and technical pattern detection`; `How hotels are stopping the 'dawn dash' for sunbeds after man wins payout` |
| Show HN | 33,290 | 13,759 | `Show HN: adamsreview - better multi-agent PR reviews for Claude Code`; `Show HN: An index of indie web/blog indexes`; `Show HN: I made a Clojure-like language in Go, boots in 7ms` |

Total live page HTML tokens common to both paths: **44,769**.

## Workflow Setup Tokens

| Setup path | Tokens |
| --- | ---: |
| Raw HN workflow corpus, one job | 24,019 |
| Raw HN workflow corpus, three repeated jobs | 72,057 |
| Smavg HN workflow brief | 1,254 |
| Exact expanded HN skill + HN workflow runbook | 3,300 |
| Smavg setup once for the three-job session | 4,554 |
| Smavg setup cold for each of three jobs | 13,662 |

Stable setup savings:

| Scenario | Without Smavg | With Smavg | Ratio |
| --- | ---: | ---: | ---: |
| Repeated raw setup for each job | 72,057 | 4,554 | 15.823x |
| Cold Smavg setup for each job | 72,057 | 13,662 | 5.274x |
| Best-case raw setup read once | 24,019 | 4,554 | 5.274x |

## End-To-End Token Accounting

This includes the live HN page HTML tokens, which Smavg does not reduce.

| Scenario | Without Smavg | With Smavg | Ratio |
| --- | ---: | ---: | ---: |
| Repeated raw setup each job + live pages | 116,826 | 49,323 | 2.369x |
| Cold Smavg setup each job + live pages | 116,826 | 58,431 | 1.999x |
| Best-case raw setup once + live pages | 68,788 | 49,323 | 1.395x |

## Exact Expansion Checks

```bash
smavg expand-context hackernews-context.json \
  skills/codex/hackernews-browsermcp/SKILL.md \
  --out /tmp/smavg-token-test-hn-skill.md

smavg expand-context hackernews-context.json \
  memories/medium-term/hackernews_browsermcp_workflow.md \
  --out /tmp/smavg-token-test-hn-workflow.md
```

Results:

- HN Codex skill: 7,411 bytes, verified PASS, `cmp` PASS.
- HN workflow runbook: 7,434 bytes, verified PASS, `cmp` PASS.

## Interpretation

Smavg helps most when repeated workflow setup is actually being reloaded.

For three repetitive HN jobs:

- Stable workflow setup dropped from 72,057 tokens to 4,554 tokens when the
  Smavg capsule was read once and exact files were expanded once.
- That is **15.823x fewer setup tokens**.
- Including live page content, the total dropped from 116,826 tokens to 49,323
  tokens, a **2.369x end-to-end reduction**.

The honest lower bound is also useful: even if a disciplined agent reads the
full raw runbook only once for the whole session, Smavg still reduces stable
setup from 24,019 tokens to 4,554 tokens, or **5.274x**. Including live page
content, that is **1.395x** end-to-end.

This confirms the intended product boundary: Smavg does not remove the need to
inspect the live website. It reduces the repeated operating knowledge around
the job.
