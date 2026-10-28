# Portable project compositions

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](./project-sharing.md)

Status: manifests, encoding/decoding, safe preview, and the local version store are `Implemented` in `2.0.0a1`, while CLI and TUI offline preview are `Experimental`. `2.0.0a4` additionally implements a replaceable offline dependency planner and independent generic-plugin load confirmation plus TUI unload controls; the explicit bridge from a host lock catalog to sandboxed package installation is included in `2.0.0a4`. Online source discovery, automatic lock generation, automatic updates, and signature trust remain `Planned` or `Reserved`.

Manifest public APIs are `CompositionManifest`, `PluginRequirement`, `encode_composition()`, `decode_composition()`, `inspect_composition()`, and `CompositionStore`. They operate on data only and perform no network access, package installation, plugin import, or execution. The installation chain separately exposes `PluginInstallCatalog`, `plan_plugin_installations()`, the replaceable `PackageInstaller`, the default `SandboxPipPackageInstaller`, and `load_installed_plugin_references()`; only explicit calls to the latter execution APIs create network, installation, or plugin-code side effects.

## Concept

A `CompositionManifest` describes how to assemble the framework. It is not a source package, virtual environment, or runtime snapshot. Users choose names and versions, for example:

```yaml
schema_version: 1
name: lucky-coding-stack
version: 2.1.0
requires_python: ">=3.11"
requires_wagent: ">=2.0,<3.0"
plugins:
  - name: wagent-openai
    version: ">=1.2,<2.0"
  - name: my-company-router
    version: "==0.4.3"
profiles:
  default: coding
policies:
  sandbox: docker
```

Users may keep several versions under one name and assign local aliases. An alias does not change a manifest's formal version.

## Code format

The first release uses a prefixed and versioned code:

```text
wagent-compose:v1:<base64url-compressed-canonical-json>:<checksum>
```

- `v1` is the encoding schema, not the user's composition version.
- Key-sorted, whitespace-free canonical JSON is zlib-compressed and Base64URL encoded.
- A SHA-256 checksum detects transmission corruption but does not identify a publisher.
- Decoding bounds compressed input and expanded JSON and rejects malformed, incomplete, or oversized payloads.
- Digital signatures and trust networks are `Reserved`.

## Allowed content

- Composition name, version, and description.
- Python and W-Agent version constraints.
- Plugin names, version constraints, and public source identifiers.
- Portable profile, routing, workflow, and tool configuration.
- Sandbox type and minimum permission requirements.
- Content digests or relative references for optional resources.

## Forbidden content

- API keys, tokens, passwords, and private keys.
- `UnsafeLocalSandbox` authorization.
- Undeclared absolute local paths.
- Arbitrary plugin source unless explicitly selected for embedding.
- Instructions to auto-install, auto-execute, or bypass confirmation.

## Export flow

```text
Current composition
  → resolve and freeze dependency constraints
  → remove secrets and retain credential references
  → validate portability
  → build a canonical manifest
  → compress, encode, and checksum
```

Export fails by default and reports the exact field when it finds a non-portable absolute path, anonymous local plugin, or embedded secret.

## Import flow

```text
Code
  → decode and verify integrity
  → validate schema version
  → build a read-only preview
  → resolve dependencies and conflicts
  → show security risk and configuration differences
  → user confirms installation
  → user confirms loading
```

Decode and preview perform no network access, install no package, import no plugin module, and execute no plugin code. Installation and loading are separate confirmation steps.

`2.0.0a4`'s `wagent plugin inspect` / `validate-load` commands and TUI Plugins screen can operate user-selected `module:attribute` YAML references. The locked installation bridge can derive a deterministic request from a composition dependency plan and a host-supplied installation catalog, then install only after the user confirms the exact request digest. The result is a verified local plugin site and entry; it is not loaded automatically. CLI `plugin validate-installed` or TUI `LOAD INSTALLED` is the second, independent code-execution confirmation boundary.

## Offline dependency plans

`2.0.0a4` can build a plan without network access, package-index queries, module imports, or package installation:

```text
wagent composition plan <code> --inventory plugin-inventory.json --json
```

The explicit candidate inventory format is:

```json
{
  "plugins": [
    {
      "name": "my-company-router",
      "version": "0.4.3",
      "source": "private-index",
      "entry": "my_router.plugin:setup"
    }
  ]
}
```

The plan checks Python and W-Agent constraints and emits `use-installed`, `install`, `change-version`, `review-source`, `select-source`, or `select-candidate` for each plugin. It describes the next step and contains no executable install command. The Python API accepts any `CompositionDependencyResolver`, so applications may connect their own lockfile, internal registry, or package format without changing the manifest core protocol.

The TUI Composition screen can read the same candidate inventory. Without one, it considers only names and versions of plugins active in the current TUI process. It never guesses that an unknown source is trusted. Even a Ready plan still requires separate plugin-code load confirmation.

## Locked package installation

The `2.0.0a4` release consumes a catalog explicitly supplied by the host. It never searches packages online or chooses versions for the user. The catalog maps source identifiers to HTTPS indexes and gives each plugin version a `module:attribute` entry plus the complete wheel dependency closure. Every package is exactly pinned and has at least one SHA-256 hash:

```json
{
  "schema_version": 1,
  "sources": [
    {"source": "pypi", "url": "https://pypi.org/simple"}
  ],
  "plugins": [
    {
      "name": "my-company-router",
      "version": "0.4.3",
      "source": "pypi",
      "entry": "my_router.plugin:setup",
      "packages": [
        {
          "name": "my-company-router",
          "version": "0.4.3",
          "sha256": ["<64-hex-wheel-sha256>"]
        }
      ]
    }
  ]
}
```

```text
wagent composition install-plan <code> --catalog install-lock.json --json
wagent composition install <code> <request-digest> \
  --catalog install-lock.json --confirm-network --confirm-package-code
wagent plugin validate-installed <installed-path> --confirm-plugin-code
```

`install-plan` is fully offline. Its review output shows the configured index scheme, host, and port, but not the full path or credentials. The default command uses `--isolated --require-hashes --only-binary=:all: --no-deps`: pip ignores extra sources from environment variables and user configuration, and accepts no sdist or unlocked dependency resolution. Global/site pip configuration inside the selected image and network proxies remain host trust concerns, so the origin preview does not prove every network request goes only to that host. Docker is the default backend and does not pull an image automatically. Unix uses the current UID/GID for the bind mount; Windows Docker Desktop uses the image user. `--backend unsafe-local --confirm-unsafe-local` is the explicitly authorized unisolated development mode. Default Docker installation mounts only a fresh staging directory; after the sandbox closes, it copies into a final directory addressed by the request digest and verifies the tree again. Index credentials must not be embedded in a URL or composition code; the default template does not read private-index credentials from pip environment variables, so hosts need a custom `PackageInstaller` for that policy.

Installation confirmation binds the composition digest, index URL, plugin entry, exact package versions, and hashes. A successful installation does not trust, import, or register plugin code; load confirmation remains separate. Before loading, the install tree is reverified; after import but before plugin setup, the entry module origin and plugin name/version are checked against the reviewed lock. The current implementation does not discover sources online, generate locks, auto-upgrade, or coordinate migration of running plugin versions.

## Version management

`CompositionStore` keeps manifests and content digests by `(name, version)`. Importing different content under the same name and version is a conflict and never silently overwrites data; an alias also cannot silently move to another version. Users can:

- Keep multiple versions and select which one runs.
- Save local changes as a new version.
- Compare plugin, configuration, and permission differences.
- Export a changed version as a new code.

An active run pins the composition digest captured at start. Updating a composition does not change running work.

## Third-party plugins

A composition code declares dependencies and does not prove trust. The offline plan shows declared source, candidate versions, and next actions but does not verify publisher identity. The locked installation view shows complete hashes, network requirements, and the package-code boundary, but SHA-256 proves only that an artifact matches the host catalog, not who published it. Generic plugin loading requires a separate one-shot code-execution confirmation. Unattended installation, online source discovery, automatic locking, and automatic updates are not implemented.
