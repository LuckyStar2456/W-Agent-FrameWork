# W-Agent 2.1.0 publication record

English | [简体中文](./acceptance-2026-10-02-release-2.1.0.md)

On 2026-10-02, stable `wagent-framework==2.1.0` was published to [PyPI](https://pypi.org/project/wagent-framework/2.1.0/) with explicit user authorization. No alpha release, Git commit or push occurred.

## Scope and acceptance basis

Includes the Harness development core accepted through M0–M5; see [release scope](./releases/2.1.0.en.md). Python packaging conventions align metadata and exported versions; bilingual documentation separates historical acceptance from confirmed upload.

Reuses [core acceptance](./harness-acceptance.en.md): 259 related tests, offline artifacts, isolated installation and three outside-repository Python/CLI/TUI examples. No new tests, installation, real-model calls or global dependency changes occurred. Only version, package description and documentation changed. All 234 Python modules match the accepted M5 wheel byte-for-byte, allowing only `__version__` to change from 2.0.0 to 2.1.0.

## Artifacts and remote confirmation

Existing tools ran `python -m build --no-isolation` in a separate temporary source directory, building sdist first and then wheel from sdist. Both artifacts passed `twine check --strict`; 234 wheel source modules and 589 sdist source/delivery files match the frozen workspace. Sensitive files and caches are excluded.

The version was confirmed absent before upload. Existing project credentials uploaded to official PyPI without exposing credential content. Version JSON confirms both artifacts are not yanked and remote hashes match local files:

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `wagent_framework-2.1.0-py3-none-any.whl` | 630830 | `cea6be92dd62817928337ec863153746dbb05d3a59c42c74aeba536251e86ff9` |
| `wagent_framework-2.1.0.tar.gz` | 1435692 | `bf1f9ad508471f98576823b09364701033261c288f1a8838556934d75009734a` |

Local directory: `C:/Users/97554/AppData/Local/Temp/wagent-release-2.1.0-dc120cdd2d174d3d90e58b2e0f620cda/dist`. This record and workspace publication status were written after upload and are not in the frozen sdist. No reinstall from PyPI was performed or claimed.

## Usage and remaining scope

```bash
python -m pip install --upgrade "wagent-framework==2.1.0"
```

Add `[models,tui]` extras when needed. The fixed core goal and publication are complete. Multi-agent systems, distributed Workflow, remote sandboxes, plugin marketplaces and advanced hot migration remain reserved. Full-suite regression, real-model quality/billing and all-platform combinations are not verified here; existing Experimental features do not automatically become stable.
