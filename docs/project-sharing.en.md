# Portable project compositions

English | [简体中文](./project-sharing.md)

Status: `Planned`. This capability lets local developers transfer a W-Agent module composition as one copyable code and manage named versions of that composition.

## Concept

A `CompositionManifest` describes how to assemble the framework. It is not a source package, virtual environment, or runtime snapshot. Users choose names and versions, for example:

```yaml
schema_version: 1
name: lucky-coding-stack
version: 2.1.0
requires:
  python: ">=3.11"
  wagent: ">=2.0,<3.0"
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

The first release plans a prefixed and versioned code:

```text
wagent-compose:v1:<base64url-compressed-canonical-json>:<checksum>
```

- `v1` is the encoding schema, not the user's composition version.
- Canonical JSON is compressed and Base64URL encoded for copying.
- A checksum detects transmission corruption but does not identify a publisher.
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

## Version management

A local index stores manifest and content digest by `(name, version)`. Importing the same name and version with a different digest is a conflict and never silently overwrites data. Users can:

- Keep multiple versions and select which one runs.
- Save local changes as a new version.
- Compare plugin, configuration, and permission differences.
- Export a changed version as a new code.

An active run pins the composition digest captured at start. Updating a composition does not change running work.

## Third-party plugins

A composition code declares dependencies and does not prove trust. Import views show plugin source, version, hash, requested capabilities, and host/network execution requirements. First loading of an unknown plugin requires confirmation; automatic updates are disabled by default.
