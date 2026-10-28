# P1 documentation acceptance and developer README

English | [简体中文](./acceptance-2026-10-01-p1-docs.md)

Date: 2026-10-01. Scope: P1 documentation cleanup and developer entry points, not P2–P4 development or republication. Result: the static documentation checks below passed; this is not new runtime or live-service acceptance.

## Changes

- Rewrote the root [Chinese README](../README.md) and [English README](../README_EN.md): positioning, installation, an offline Python quickstart, extension navigation, CLI/TUI, safety boundaries and contribution entry points. Release-process narrative is no longer the starting point, and users need not build a candidate package first.
- Standardized version-scope headers across 53 bilingual topic pairs and corrected prose describing shipped features as candidate or unreleased. `Experimental` / `Planned` / `Reserved` distinctions remain; publication does not promote API stability.
- Corrected the installation guide and documentation index: separate published-package usage from source development; do not assume a wheel contains `examples`; clarify that `wagent init` only creates directories and empty configuration, requiring separate model setup and authorization before a real request.
- Corrected Runtime accounting status: a unified observation ledger and Run/Session links exist; host-operation totals are not exact per-Run usage and reconciliation is not automatic.
- Clarified roadmap approval scope: single-agent/local-workflow approvals and recovery exist; approval coordination across multiple agents remains reserved.
- Updated current architecture, API, developer and plugin-replacement version descriptions and linked release evidence. Historical release notes and older acceptance reports were not rewritten.

## Method and results

This round used file reads, source-signature inspection, standard-library AST parsing, Markdown local-link/heading checks, SHA-256 comparison and Git whitespace checks only. The temporary checker does not import the project or execute the README example. No pytest, compilation, installation, build, model call, service acceptance, Git commit/push or package publication was performed.

| Check | Result and boundary |
|---|---|
| Local documentation links and heading fragments | Across 120 documents, 1,145 local links including 10 heading fragments passed; this does not check remote website availability |
| Bilingual pairing | All 59 top-level document pairs and the root README have Chinese/English counterparts; the main rewritten pages were compared for meaning, without claiming automated verification of all translation quality |
| README example | Identical bilingual code; `ast.parse` passed; all 19 imports exist in public source. Constructor signatures, registration-handle cleanup and result fields were inspected. Output is labeled expected, not executed |
| Installation and CLI | Version 2.0.0, Python 3.11+ and all 10 extras match `setup.py`; entry-page commands/options were compared with CLI source, not executed |
| Current status prose | Candidate/unreleased contradictions in nonhistorical pages were removed; technical routing/dependency candidates were preserved |
| Non-documentation and historical protection | All 411 pre-recorded source, test, example, package-configuration and historical-document SHA-256 values remained unchanged |
| Whitespace | `git diff --check` passed; unrelated existing worktree changes were not reverted or committed |

## References and design choices

README organization draws on [smolagents](https://github.com/huggingface/smolagents#readme) for concise positioning, installation and quick examples, and [LangGraph](https://github.com/langchain-ai/langgraph#readme) for capability descriptions and documentation navigation. Only structure was borrowed, not prose, code or performance claims. `python-patterns` informed the asynchronous entry point, public-API usage and explicit registration lifecycle.

## Remaining scope

- P1 static documentation acceptance is complete. Executing the new README example against an installed package remains unverified and needs separate authorization.
- P2: support/coding developer paths; P3: error/configuration experience; P4: Python/CLI/TUI experience consistency. None was advanced this round.
- Live vendor/billing acceptance and other enhancements remain in the [roadmap](./roadmap.en.md), not implied by these documentation results.
- Changes exist only in the local worktree. Git remotes and the published PyPI 2.0.0 long description/artifacts are unchanged. Prior release verification remains documented in the [release record](./acceptance-2026-10-01-stable-release.en.md).
