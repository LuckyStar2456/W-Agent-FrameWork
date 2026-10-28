# Harness core final acceptance (M5)

English | [简体中文](./harness-acceptance.md)

> Release scope: the new framework core described here is included in 2.1.0. Earlier “unpublished” labels and candidate 2.0.0 metadata below record pre-release stages, not the 2.1.0 package status. See [2.1.0 notes](./releases/2.1.0.en.md); upload status is on [PyPI](https://pypi.org/project/wagent-framework/2.1.0/).

Date: 2026-10-02. Scope: current unpublished source and local candidate artifacts, not a claim that PyPI 2.0.0 contains these additions. The [fixed baseline](./harness-core.en.md) governs this gate, not the entire library or every external service.

## Acceptance matrix

| Item | Implementation and evidence entry | Current status |
|---|---|---|
| H01 Decorator development | Support example; `test_application_decorators.py` and startup-failure/ordered-cleanup delivery tests | Accepted within the scope below |
| H02 Custom Harness | Out-of-repository custom/support/coding; Loop/router/executor replacement in `test_local_application.py` | Accepted within the scope below |
| H03 Aspect lifecycle | `test_application_aspects.py`: sync/async, errors, cancellation and stream closure | Accepted within the scope below |
| H04 Equivalent assembly | Planning/decorator/configuration cases plus three-mode failed-start cleanup | Accepted within the scope below |
| H05 Optional defaults | Custom example without ReAct; subprocess blocks optional HTTP/TUI dependency imports | Accepted within the scope below |
| H06 Unprivileged frontends | Three installed projects via Python/CLI/headless TUI; removing tracing preserves coding approval | Accepted within the scope below |
| H07 Reproducible docs | Bilingual README/tutorials; `tests/acceptance/harness_delivery.py` verifies installed provenance | Accepted within the scope below |
| H08 Single ownership | Context/Plugin/Host cancellation, borrowing, unload and custom scope-order regressions | Accepted within the scope below |

Run related tests/static checks automatically after completing the stage, not the full suite. The user separately authorized offline wheel/sdist building, a new isolated environment, cached/local dependencies only, and outside-repository examples plus CLI/TUI acceptance. No global changes, external services or publication.

## Implementation scope

Three offline developer tutorials/examples and bilingual README, architecture, API and migration updates. Plugin bridging now accepts `scope_order`, preserving the same hierarchy during preflight and actual context creation. Coding checks approval digests and original content at the tool boundary; aspects only trace.

## Verification record

Stage-related tests ran offline in the existing project-isolated Python 3.11.9 environment:

- Core and delivery: 203 passed / 4.47s across `test_harness_delivery`, `test_application_execution`, `test_application_frontends`, `test_local_application`, `test_application_planning`, `test_application_context`, `test_application_decorators`, `test_application_aspects`, `test_application_configuration`, `test_application_legacy` and `test_application_plugins`.
- Adjacent plugins: 56 passed / 5.51s across `test_kernel_plugins`, `test_plugin_cancellation`, `test_plugin_replacement` and `test_plugin_replacement_session`.
- Total: 259 distinct cases. Commands use two explicit file groups: `python -m pytest tests/<listed-name>.py ... -q`. This is not the full suite, nor additive with M4's historical 572.
- AST/in-memory compilation passed for 33 related Python files. Local link target existence was checked across 28 bilingual entry/tutorial documents (not heading anchors). Both complete README Python quickstarts executed and printed `HELLO FRAMEWORK`.

Artifact acceptance uses temporary directory `wagent-m5-453ccba78c2447f2ba07d961e8320ac6`:

1. Copy build inputs into a separate source directory and use existing build tools with `python -m build --no-isolation --sdist --wheel`, without modifying global dependencies.
2. Recover original wheel archives from the local pip HTTP cache. Install the candidate wheel's `tui` extra with `--no-index --only-binary=:all: --find-links <wheelhouse>` into a new `installed` environment that does not inherit global packages. No model HTTP extra was installed.
3. Verify all 234 Python modules in the wheel against source and 14 delivery files in sdist (bilingual README/tutorials/acceptance, three examples, JSON inputs and runner). Examples are absent from the wheel; no .env, credential file or cache is included.
4. Run the standalone runner from `outside`; the package originates at `installed/Lib/site-packages/w_agent/__init__.py`. All three script entries, lifecycle demos and Python/CLI/headless-TUI paths pass. The full TUI mounts, and both installed `wagent`/`w-agent` command entries pass. Docker probing is explicitly disabled in this TUI smoke check.
5. `pip check` reports `No broken requirements found.` The first offline resolution exposed universal cached-wheel names marked py2; selecting the archive's advertised py3 tag without changing archive bytes fixed resolution. The runner's Windows subprocess encoding was made consistently UTF-8 before both help-output checks passed. These were acceptance-tool corrections, not framework test failures.

After synchronizing acceptance records, rebuild and recheck the final local candidate installation and outside-repository execution. Artifact-check output in the temporary directory records local hashes; these are not PyPI artifacts. Build output contains only legacy license-classifier/empty optional-file-pattern notices and exits successfully.

## Remaining boundaries and next steps

- Unpublished. Local artifact metadata remains 2.0.0 solely as a current-source candidate, not the same artifact as PyPI 2.0.0. A release needs separate versioning and approval.
- No real model, billing quality, external MCP/vector service or new Docker acceptance; no full-suite regression. TUI checks are headless interactions, not manual terminal appearance acceptance.
- Examples use deterministic stand-ins and memory data. Coding executes no generated code; an approval digest is not authentication. Ordinary Python/aspects/plugins are trusted host code, not a sandbox.
- Host manages only submitted tasks/streams. Uncooperative synchronous code, independently spawned tasks and arbitrary Python stack recovery are not guaranteed. Calls create child scopes, not automatically persistent Session scopes.
- `replace_components` validates pre-start replacements, without graph pruning or live-object hot swaps. Legacy container/proxy behavior requires opt-in migration.
- Multi-agent systems, distributed Workflow, remote sandboxes, plugin marketplaces and advanced hot migration remain reserved. New vendor templates, advanced knowledge strategies and media/TUI decoration remain deferred; see the [roadmap](./roadmap.en.md).
