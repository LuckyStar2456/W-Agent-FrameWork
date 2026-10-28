# 2.0 stable-release baseline

English | [简体中文](./stable-release-baseline.md)

Status: **stable `2.0.0` published on 2026-10-01**. Both [PyPI](https://pypi.org/project/wagent-framework/2.0.0/) artifact digests match the accepted candidates; see [final acceptance/publication](./acceptance-2026-10-01-stable-release.en.md). B01–B12 are closed. Enhancements follow without relabeling Experimental APIs as stable.

## Fixed scope

This is the basic release gate for the [roadmap](./roadmap.en.md), not a replacement for detailed capability statuses. Closure does not mean the entire enhancement roadmap or every live service/platform is accepted.

| ID | Basic deliverable | Completion criterion and current gap |
|---|---|---|
| B01 | Python 3.11+, `w_agent`, minimal 1.x compatibility | Complete; compatibility regressions, 216 source-module artifact comparison and isolated imports passed |
| B02 | Replaceable protocols, unified registry, four plugin entries | Python/decorator/YAML/entry-point assembly and unloading; cancellation cleanup fixed, 76 related plugin tests passed |
| B03 | Models, generic HTTP, routing and probing | Eight vendor groups and HTTP mappings present; false probe evidence fixed, 50 related tests passed; no claim of live vendor acceptance |
| B04 | Single-Agent ReAct/tool loop | Model→tool→model, exact approval, cancellation, bounded budgets and final result; actual support/coding composition and 12 related tests passed; see [starter](./basic-development.en.md) |
| B05 | Workflow | Complete; DAG, state graph, Python composition and supported boundary recovery regressions passed; not arbitrary instruction-level resumption |
| B06 | Basic tools and MCP | Complete; adapters, permissions/approvals and MCP client focused regressions passed; not a complete IDE or MCP hosting platform |
| B07 | Basic knowledge/RAG | Complete; local ingestion/snapshots/retrieval/Agent/Workflow composition passed in source and installed package; remote vectors remain separately qualified |
| B08 | Run/Session and usage | Complete; durable records, approval recovery, input/output token and budget regressions passed; unknown usage/pricing is not zero or exact billing |
| B09 | Safe local execution | Docker isolation and explicitly authorized unsafe-local; live Docker 29.2.1 cached-image smoke passed this batch, no image pulls or silent fallback |
| B10 | Project sharing/versioning | Complete; code/preview/named-version/conflict regressions passed; codes do not automatically transfer or trust arbitrary source |
| B11 | CLI/TUI and basic evaluation | Complete; installed CLI aliases, support/coding examples and TUI character art/emoticons/wide/narrow/resize passed |
| B12 | Documentation, examples and artifacts | Complete; bilingual docs, strict artifact checks, isolated install, 46 package regressions, live Docker, upload and remote digests passed |

## Closing sequence (completed)

1. Fix confirmed B02/B03 defects; add B04 support/coding composition tests and a copyable tutorial.
2. Run the authorized focused core tests, not the full suite. Record commands/results per group; do not reuse historical pass counts.
3. With an available Docker environment, run `tests/integration_docker_smoke.py` using a cached image and no pulls. Starting Docker or additional installation requires the user's decision.
4. Update stable metadata, build wheel/sdist, install the local candidate into a temporary isolated environment outside the checkout, and verify imports, dependency consistency and CLI/TUI. Upload the stable release only after passing; changing a version number is not completion.

No live model calls, global dependency installation or automatic Git commit/push in this batch. Live vendor quality/billing and every platform combination remain unverified and must not be described as accepted.

## After the stable release: enhancements and reserved designs

These are not additional gates. Existing experimental implementations do not automatically become stable because they ship in a stable package:

- Models/accounting: additional vendor multimedia details, native cursors across all frontends, automatic price updates and exact cross-service per-Run attribution.
- Knowledge/storage: semantic splitting, archive GC/encryption, cross-database atomic transactions, automatic remote reconciliation and advanced index maintenance.
- Plugins/sharing: live consumer rebinding/state migration, online marketplace, automatic updates, cross-language plugin SDK and signed trust network.
- Execution/orchestration: other Agent styles, multi-Agent, distributed/nested workflows, general remote sandbox and all-platform Wasmer/nsjail acceptance.
- Interaction: richer media playback, specialized voice flows and hosted evaluation.

Still out of scope: hosted platform, tenancy, organization/cloud billing and automatically executing third-party code from sharing codes. A confirmed defect violating the basic commitments may block release; new enhancement ideas go to the roadmap without expanding this baseline.
