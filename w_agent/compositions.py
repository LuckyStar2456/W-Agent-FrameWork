"""Portable, non-executing framework composition manifests."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import re
import zlib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Any, Mapping
from urllib.parse import urlsplit

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

COMPOSITION_PREFIX = "wagent-compose:v1:"
_MAX_COMPRESSED = 256 * 1024
_MAX_JSON = 1024 * 1024
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class CompositionError(ValueError):
    """A composition is invalid, unsafe to preview, or conflicts locally."""


@dataclass(frozen=True, slots=True)
class PluginRequirement:
    name: str
    version: str = ""
    source: str | None = None

    def __post_init__(self) -> None:
        if not _SAFE_NAME.fullmatch(self.name):
            raise CompositionError("plugin name is not portable")
        if self.version:
            _specifier(self.version, "plugin version")
        if self.source is not None:
            _validate_portable(self.source, f"plugins.{self.name}.source")
            if self.source.lower().startswith("file:"):
                raise CompositionError("plugin source cannot be a local file URL")
            parsed = urlsplit(self.source)
            if parsed.username is not None or parsed.password is not None:
                raise CompositionError("plugin source cannot contain credentials")


@dataclass(frozen=True, slots=True)
class CompositionManifest:
    name: str
    version: str
    description: str = ""
    requires_python: str = ">=3.11"
    requires_wagent: str = ">=2.0,<3.0"
    plugins: tuple[PluginRequirement, ...] = ()
    profiles: Mapping[str, Any] = field(default_factory=dict)
    policies: Mapping[str, Any] = field(default_factory=dict)
    routing: Mapping[str, Any] = field(default_factory=dict)
    workflows: Mapping[str, Any] = field(default_factory=dict)
    tools: Mapping[str, Any] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise CompositionError("unsupported manifest schema version")
        if not _SAFE_NAME.fullmatch(self.name):
            raise CompositionError("composition name is not portable")
        try:
            Version(self.version)
        except InvalidVersion as error:
            raise CompositionError("composition version is invalid") from error
        _specifier(self.requires_python, "Python requirement")
        _specifier(self.requires_wagent, "W-Agent requirement")
        object.__setattr__(self, "plugins", tuple(self.plugins))
        for attribute in ("profiles", "policies", "routing", "workflows", "tools"):
            value = dict(getattr(self, attribute))
            _validate_portable(value, attribute)
            object.__setattr__(self, attribute, _freeze_json(value))
        sandbox = self.policies.get("sandbox")
        sandbox_type = sandbox.get("type") if isinstance(sandbox, Mapping) else sandbox
        if str(sandbox_type).lower() in {"unsafe-local", "unsafe_local", "local"}:
            raise CompositionError("composition cannot grant unsafe local execution")


@dataclass(frozen=True, slots=True)
class CompositionPreview:
    manifest: CompositionManifest
    digest: str
    plugin_dependencies: tuple[str, ...]
    risks: tuple[str, ...]


def encode_composition(manifest: CompositionManifest) -> str:
    payload = _canonical(manifest)
    if len(payload) > _MAX_JSON:
        raise CompositionError("composition manifest is too large")
    compressed = zlib.compress(payload, level=9)
    if len(compressed) > _MAX_COMPRESSED:
        raise CompositionError("composition code is too large")
    encoded = base64.urlsafe_b64encode(compressed).rstrip(b"=").decode("ascii")
    return f"{COMPOSITION_PREFIX}{encoded}:{hashlib.sha256(payload).hexdigest()}"


def decode_composition(code: str) -> CompositionManifest:
    if not code.startswith(COMPOSITION_PREFIX):
        raise CompositionError("unsupported composition-code prefix")
    body = code[len(COMPOSITION_PREFIX) :]
    try:
        encoded, expected = body.rsplit(":", 1)
        compressed = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    except Exception as error:
        raise CompositionError("composition code is malformed") from error
    if len(compressed) > _MAX_COMPRESSED:
        raise CompositionError("composition code is too large")
    decompressor = zlib.decompressobj()
    try:
        payload = decompressor.decompress(compressed, _MAX_JSON + 1)
    except zlib.error as error:
        raise CompositionError("composition payload is invalid") from error
    if (
        len(payload) > _MAX_JSON
        or decompressor.unconsumed_tail
        or not decompressor.eof
    ):
        raise CompositionError("composition payload is too large or incomplete")
    actual = hashlib.sha256(payload).hexdigest()
    if not hmac.compare_digest(actual, expected):
        raise CompositionError("composition checksum mismatch")
    try:
        data = json.loads(payload)
        return _manifest_from_data(data)
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise CompositionError("composition manifest is malformed") from error


def inspect_composition(code: str) -> CompositionPreview:
    manifest = decode_composition(code)
    digest = hashlib.sha256(_canonical(manifest)).hexdigest()
    risks = []
    if manifest.plugins:
        risks.append("third-party-plugins-require-confirmation")
    sandbox = manifest.policies.get("sandbox")
    if sandbox not in (None, "none", {"type": "none"}):
        risks.append("sandbox-policy-requires-review")
    return CompositionPreview(
        manifest,
        digest,
        tuple(f"{item.name}{item.version}" for item in manifest.plugins),
        tuple(risks),
    )


class CompositionStore:
    """Local named/versioned manifest store with conflict-safe aliases."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, manifest: CompositionManifest, *, alias: str | None = None) -> str:
        digest = hashlib.sha256(_canonical(manifest)).hexdigest()
        directory = self.root / manifest.name / manifest.version
        path = directory / "manifest.json"
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise CompositionError("same composition name/version has different content")
        directory.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            _atomic_write(path, _canonical(manifest))
        if alias is not None:
            if not _SAFE_NAME.fullmatch(alias):
                raise CompositionError("composition alias is not portable")
            aliases = self._aliases()
            target = f"{manifest.name}@{manifest.version}"
            if alias in aliases and aliases[alias] != target:
                raise CompositionError("composition alias already points elsewhere")
            aliases[alias] = target
            _atomic_write(self.root / "aliases.json", _json_bytes(aliases))
        return digest

    def load(self, name: str, version: str | None = None) -> CompositionManifest:
        if version is None:
            target = self._aliases().get(name)
            if target is None:
                raise CompositionError("composition alias does not exist")
            name, version = target.rsplit("@", 1)
        _validate_store_identity(name, version)
        path = self.root / name / version / "manifest.json"
        if not path.is_file():
            raise CompositionError("composition version does not exist")
        return _manifest_from_data(json.loads(path.read_text(encoding="utf-8")))

    def versions(self, name: str) -> tuple[str, ...]:
        if not _SAFE_NAME.fullmatch(name):
            raise CompositionError("composition name is not portable")
        directory = self.root / name
        if not directory.is_dir():
            return ()
        return tuple(
            sorted(
                (item.name for item in directory.iterdir() if item.is_dir()),
                key=Version,
            )
        )

    def entries(self) -> tuple[tuple[str, str], ...]:
        """List stored composition identities without loading plugin code."""

        entries: list[tuple[str, str]] = []
        for directory in self.root.iterdir():
            if directory.is_dir() and _SAFE_NAME.fullmatch(directory.name):
                entries.extend(
                    (directory.name, version)
                    for version in self.versions(directory.name)
                )
        return tuple(entries)

    def _aliases(self) -> dict[str, str]:
        path = self.root / "aliases.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _canonical(manifest: CompositionManifest) -> bytes:
    return _json_bytes(manifest_to_dict(manifest))


def manifest_to_dict(manifest: CompositionManifest) -> dict[str, Any]:
    """Return a detached, JSON-compatible manifest mapping."""

    return {
        "name": manifest.name,
        "version": manifest.version,
        "description": manifest.description,
        "requires_python": manifest.requires_python,
        "requires_wagent": manifest.requires_wagent,
        "plugins": [
            {"name": item.name, "version": item.version, "source": item.source}
            for item in manifest.plugins
        ],
        "profiles": _thaw_json(manifest.profiles),
        "policies": _thaw_json(manifest.policies),
        "routing": _thaw_json(manifest.routing),
        "workflows": _thaw_json(manifest.workflows),
        "tools": _thaw_json(manifest.tools),
        "schema_version": manifest.schema_version,
    }


def manifest_from_dict(data: Mapping[str, Any]) -> CompositionManifest:
    """Validate an untrusted JSON-compatible manifest mapping."""

    return _manifest_from_data(data)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _manifest_from_data(data: Mapping[str, Any]) -> CompositionManifest:
    values = dict(data)
    values["plugins"] = tuple(
        PluginRequirement(**item) for item in values.get("plugins", ())
    )
    return CompositionManifest(**values)


def _validate_portable(value: Any, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if _secret_key(normalized):
                raise CompositionError(f"secret material is forbidden at {path}.{key}")
            if normalized in {"source_code", "plugin_code", "executable_code"}:
                raise CompositionError(f"embedded code is forbidden at {path}.{key}")
            _validate_portable(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _validate_portable(item, f"{path}[{index}]")
    elif isinstance(value, str) and (
        PureWindowsPath(value).is_absolute()
        or PurePosixPath(value).is_absolute()
        or value.lower().startswith("file:")
    ):
        raise CompositionError(f"absolute local path is forbidden at {path}")
    elif isinstance(value, float) and not math.isfinite(value):
        raise CompositionError(f"non-finite number is forbidden at {path}")
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        raise CompositionError(f"non-JSON value is forbidden at {path}")


def _specifier(value: str, label: str) -> None:
    try:
        SpecifierSet(value)
    except InvalidSpecifier as error:
        raise CompositionError(f"{label} is invalid") from error


def _secret_key(value: str) -> bool:
    if value.endswith(("_ref", "_reference", "_env")):
        return False
    return value in {"authorization", "secret"} or value.endswith(
        ("_api_key", "_token", "_password", "_private_key", "_secret")
    ) or value in {"api_key", "token", "password", "private_key"}


def _validate_store_identity(name: str, version: str) -> None:
    if not _SAFE_NAME.fullmatch(name):
        raise CompositionError("composition name is not portable")
    try:
        Version(version)
    except InvalidVersion as error:
        raise CompositionError("composition version is invalid") from error


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _atomic_write(path: Path, payload: bytes) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
