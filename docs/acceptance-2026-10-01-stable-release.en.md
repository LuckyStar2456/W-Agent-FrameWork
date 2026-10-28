# 2026-10-01 stable acceptance and publication

English | [简体中文](./acceptance-2026-10-01-stable-release.md)

Result: **stable `wagent-framework==2.0.0` is published** on [PyPI](https://pypi.org/project/wagent-framework/2.0.0/). No new alpha, full-suite run, live model call, global dependency modification or Git commit/push occurred.

The user authorized focused core tests, wheel/sdist builds, temporary isolated local-package installation and publication after passing, then changed the target to stable and authorized background Docker startup with cached images only.

## Scope and fixes

[Baseline B01–B12](./stable-release-baseline.en.md) is closed. Audits found two basic defects, not missing architectural modules:

- Local model catalogs no longer prove connectivity/authentication. Custom mapping evidence comes from the actual request path in an isolated task context. A remote catalog proves catalog connectivity only.
- Plugin loading/unloading/replacement/notification cancellation converges owned resources before propagation, including repeated cancellation. Dependency cleanup failure does not start a replacement; explicit manager close can converge remaining plugins.

Added actual support/coding template→tool→result examples and permission/lifecycle tests. The `python-patterns` skill informed replaceable protocols, explicit effects and cancellation/error propagation. Six bilingual entry documents were reorganized; topic docs distinguish historical states from current source without promoting all Experimental APIs.

## Focused source checks

Python 3.11.9 in the existing clean project environment. Groups overlap and are not a unique-test total:

| Group | Result | Coverage |
|---|---:|---|
| Core chain | 282 passed / 163.65s | 20 files: ReAct, tools, Runtime, Workflow, knowledge, compatibility, CLI/TUI, Session, model execution, sharing, sandbox, MCP and package integrity |
| Plugin fixes | 76 passed / 13.12s | cancellation, kernel plugins/loading, replacement/session, installation |
| Probe fixes | 50 passed | evidence, probing, HTTP templates, OpenAI-compatible, routing |
| Neighboring accounting | 91 passed | budget evaluation/probe, service-usage frontends/runtime, Runtime shared budget |
| Template composition | 12 passed / 1.98s | basic development, agent templates, framework acceptance |
| Foundation/budget | 84 passed / 8.32s | registry/events, lifecycle/AOP/component chain, SQLite budget, usage links/resume, evaluation |
| Post-version cross-check | 45 passed / 2.41s | package integrity, probe evidence, plugin cancellation, basic development |

Source `integration_tui_smoke.py` passed at 120×42 and 45×30, including character art/emoticons and resize-back. SVGs were generated for review; automated assertions are not described as manual inspection of every screen.

## Artifacts and isolated installation

Existing build tools were used without installing/modifying global tools. `python -m build --no-isolation` built sdist and then wheel from sdist. An initial build overlapped documentation closeout; only the rebuilt frozen artifacts were published.

- Final artifact directory: `C:/Users/97554/AppData/Local/Temp/wagent-stable-2.0.0-72c3fb1c9fd9484dad400cc5aa3b0e74/frozen-dist`.
- All 216 `w_agent` Python sources matched the frozen source byte-for-byte in wheel/sdist, with no missing/extra Python modules.
- Sdist docs matched the freeze; version, Python requirement, Stable classifier, CLI aliases and README metadata passed inspection.
- No `.env`, `wagent-pypi.txt`, `.pypirc`, credential directories, bytecode or caches; both artifacts passed `twine check --strict`.
- Created a venv without global site-packages; installed the exact local wheel with `models,tui,testing` extras; `pip check` passed.
- Outside the repository, `python -I` confirmed imports from the new environment's `site-packages`.
- After copying five test files and their helper modules, installed-package regressions passed **46 / 2.44s**. Initial collection lacked test helpers; copying them fixed the test harness, not framework imports.
- Both CLI aliases reported 2.0.0. Support/coding examples each completed in 2 steps with 1 tool call. Installed-package TUI wide/narrow/resize-back passed.

Installed-package regression command, in a smoke directory containing test assets but no `w_agent` source:

```text
python -I -m pytest -q -o pythonpath=. tests/test_package_integrity.py tests/test_model_probe_evidence.py tests/test_plugin_cancellation.py tests/test_basic_development.py tests/test_framework_acceptance.py
```

## Live Docker

After authorized Docker Desktop startup, Linux engine 29.2.1 became reachable. Source and installed package each ran `integration_docker_smoke.py` using only cached:

```text
node@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32
```

Network isolation, read-only root/workspace, UID 65534, dropped capabilities, no-new-privileges, 512 MiB memory, temporary writes, explicit environment, timeout and cleanup passed. No pull or unsafe fallback. No `wagent-release-smoke` containers remained. Docker Desktop remains running; other project containers were not modified.

## Publication and remote verification

Before upload, verified 2.0.0 did not exist and artifact digests were unchanged. Existing project credentials were used without displaying their contents. After upload, PyPI version JSON showed both files non-yanked and these digests exactly matching the accepted candidates:

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `wagent_framework-2.0.0-py3-none-any.whl` | 586455 | `1a2abe9a99bc232969e545f062cef101e7445b1496a90d495040843a56f27897` |
| `wagent_framework-2.0.0.tar.gz` | 1298525 | `35a51b6ea5685e0a881e90719ba4fa9f9797cad9804732de569229a80691ed38` |

This record and post-upload checklist statuses were written afterward and are not inside the frozen sdist. Published Python sources did not change. No claim of another install from PyPI is made: evidence is installation of the exact local candidate plus identical remote digests.

## Remaining scope

No basic-release blockers remain; the framework is not declared permanently finished. Enhancements/Reserved designs include more native cursors/multimedia, advanced knowledge maintenance, online plugin updates/migration, further orchestration/sandbox styles and media/voice. See the baseline and [roadmap](./roadmap.en.md). Live model billing, remote vector stores and all-platform combinations were not verified this batch. Future tests/installations/releases still require the user's decision.
