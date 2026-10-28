"""Locked, sandboxed package installation for portable plugin compositions.

The composition manifest remains a declarative, non-executing document.  This
module adds an explicit bridge from an offline dependency plan to a package
installation request.  Installation and plugin-code loading remain separate
authorization boundaries.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Protocol
from urllib.parse import urlsplit

from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from w_agent.composition_planning import (
    CompositionPlan,
    CompositionPluginAction,
)
from w_agent.compositions import CompositionError, PluginRequirement
from w_agent.kernel import (
    Plugin,
    PluginHandle,
    PluginLoadError,
    PluginManager,
    PluginReference,
    load_plugin_references,
)
from w_agent.models import CancellationToken
from w_agent.sandbox import (
    SandboxCommand,
    SandboxNetwork,
    SandboxProvider,
    SandboxSpec,
    WorkspaceAccess,
)


_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_DISTRIBUTION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_AUTHORIZATION_SENTINEL = object()
_PROVENANCE_FILE = ".wagent-install.json"


class PluginInstallationError(RuntimeError):
    """A locked plugin installation could not be planned or completed safely."""


@dataclass(frozen=True, slots=True)
class LockedPackage:
    """One exact wheel requirement and its accepted SHA-256 artifact hashes."""

    name: str
    version: str
    sha256: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not _DISTRIBUTION.fullmatch(self.name):
            raise CompositionError("locked package name is invalid")
        if not isinstance(self.version, str):
            raise CompositionError("locked package version must be a string")
        try:
            Version(self.version)
        except InvalidVersion as error:
            raise CompositionError("locked package version is invalid") from error
        hashes = tuple(str(item).lower() for item in self.sha256)
        if not hashes or any(not _SHA256.fullmatch(item) for item in hashes):
            raise CompositionError("locked package needs valid SHA-256 hashes")
        if len(hashes) != len(set(hashes)):
            raise CompositionError("locked package SHA-256 hashes must be unique")
        object.__setattr__(self, "sha256", hashes)

    @property
    def canonical_name(self) -> str:
        return canonicalize_name(self.name)

    def requirement_line(self) -> str:
        hashes = " ".join(f"--hash=sha256:{item}" for item in self.sha256)
        return f"{self.name}=={self.version} {hashes}"


@dataclass(frozen=True, slots=True)
class PluginPackageLock:
    """Exact package closure and import entry for one plugin version."""

    name: str
    version: str
    source: str
    entry: str
    packages: tuple[LockedPackage, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.version, str):
            raise CompositionError("plugin lock version must be a string")
        try:
            Version(self.version)
        except InvalidVersion as error:
            raise CompositionError("plugin lock version is invalid") from error
        if not isinstance(self.source, str) or not self.source.strip():
            raise CompositionError("plugin lock source must not be empty")
        PluginRequirement(self.name, source=self.source)
        PluginReference(self.entry)
        packages = tuple(self.packages)
        if not packages or not all(isinstance(item, LockedPackage) for item in packages):
            raise CompositionError("plugin lock needs at least one locked package")
        names = [item.canonical_name for item in packages]
        if len(names) != len(set(names)):
            raise CompositionError("plugin lock package names must be unique")
        object.__setattr__(self, "source", self.source.strip())
        object.__setattr__(self, "packages", packages)


@dataclass(frozen=True, slots=True)
class PackageIndex:
    """Host-selected mapping from a public source identifier to a package index."""

    source: str
    url: str
    allow_insecure: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or not self.source.strip():
            raise CompositionError("package index source must not be empty")
        if (
            not isinstance(self.url, str)
            or not self.url.strip()
            or any(character in self.url for character in ("\0", "\r", "\n"))
        ):
            raise CompositionError("package index URL is invalid")
        if not isinstance(self.allow_insecure, bool):
            raise CompositionError("package index allow_insecure must be a boolean")
        try:
            parsed = urlsplit(self.url)
            if parsed.port == 0:
                raise ValueError("package index port must be positive")
        except ValueError as error:
            raise CompositionError("package index URL is invalid") from error
        if parsed.scheme not in {"https", "http"} or not parsed.hostname:
            raise CompositionError("package index URL must be HTTP(S)")
        if parsed.username is not None or parsed.password is not None:
            raise CompositionError("package index URL cannot contain credentials")
        if parsed.query or parsed.fragment:
            raise CompositionError("package index URL cannot contain query or fragment")
        if parsed.scheme != "https" and not self.allow_insecure:
            raise CompositionError("insecure package index needs explicit opt-in")
        object.__setattr__(self, "source", self.source.strip())
        object.__setattr__(self, "url", self.url.strip().rstrip("/"))

    @property
    def origin(self) -> str:
        """Expose the network destination without catalog path details."""

        parsed = urlsplit(self.url)
        return f"{parsed.scheme}://{parsed.netloc}"


@dataclass(frozen=True, slots=True)
class PluginInstallCatalog:
    """Strict, caller-supplied offline package locks and source mappings."""

    sources: tuple[PackageIndex, ...]
    plugins: tuple[PluginPackageLock, ...]

    def __post_init__(self) -> None:
        sources = tuple(self.sources)
        plugins = tuple(self.plugins)
        if not all(isinstance(item, PackageIndex) for item in sources):
            raise CompositionError("package indexes must be PackageIndex values")
        if not all(isinstance(item, PluginPackageLock) for item in plugins):
            raise CompositionError("plugin locks must be PluginPackageLock values")
        source_names = [item.source for item in sources]
        plugin_ids = [(item.name, item.version, item.source) for item in plugins]
        if len(source_names) != len(set(source_names)):
            raise CompositionError("package index sources must be unique")
        if len(plugin_ids) != len(set(plugin_ids)):
            raise CompositionError("plugin package locks must be unique")
        object.__setattr__(self, "sources", sources)
        object.__setattr__(self, "plugins", plugins)


@dataclass(frozen=True, slots=True)
class PluginInstallRequest:
    """One deterministic package installation request bound to a composition."""

    composition_digest: str
    lock: PluginPackageLock
    index: PackageIndex

    def __post_init__(self) -> None:
        if not isinstance(self.lock, PluginPackageLock) or not isinstance(
            self.index, PackageIndex
        ):
            raise CompositionError("plugin install request values are invalid")
        if not isinstance(self.composition_digest, str) or not _SHA256.fullmatch(
            self.composition_digest
        ):
            raise CompositionError("composition digest is invalid")
        if self.lock.source != self.index.source:
            raise CompositionError("plugin lock and package index source differ")

    @property
    def digest(self) -> str:
        payload = {
            "composition_digest": self.composition_digest,
            "plugin": {
                "name": self.lock.name,
                "version": self.lock.version,
                "source": self.lock.source,
                "entry": self.lock.entry,
            },
            "index_url": self.index.url,
            "packages": [
                {
                    "name": item.name,
                    "version": item.version,
                    "sha256": list(item.sha256),
                }
                for item in self.lock.packages
            ],
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class PluginInstallBlocker:
    plugin_name: str | None
    reason: str

    def __post_init__(self) -> None:
        if self.plugin_name is not None and (
            not isinstance(self.plugin_name, str) or not self.plugin_name.strip()
        ):
            raise CompositionError("plugin install blocker name is invalid")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise CompositionError("plugin install blocker reason is invalid")


@dataclass(frozen=True, slots=True)
class PluginInstallationPlan:
    """Prompt-free projection between dependency review and package execution."""

    composition_digest: str
    requests: tuple[PluginInstallRequest, ...]
    blockers: tuple[PluginInstallBlocker, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.composition_digest, str) or not _SHA256.fullmatch(
            self.composition_digest
        ):
            raise CompositionError("plugin installation plan digest is invalid")
        requests = tuple(self.requests)
        blockers = tuple(self.blockers)
        if not all(isinstance(item, PluginInstallRequest) for item in requests):
            raise CompositionError("plugin installation plan requests are invalid")
        if not all(isinstance(item, PluginInstallBlocker) for item in blockers):
            raise CompositionError("plugin installation plan blockers are invalid")
        request_ids = [item.digest for item in requests]
        if len(request_ids) != len(set(request_ids)):
            raise CompositionError("plugin installation plan requests must be unique")
        object.__setattr__(self, "requests", requests)
        object.__setattr__(self, "blockers", blockers)

    @property
    def installable(self) -> bool:
        return not self.blockers


def plan_plugin_installations(
    plan: CompositionPlan,
    catalog: PluginInstallCatalog,
) -> PluginInstallationPlan:
    """Resolve locked install requests without network, imports, or execution."""

    indexes = {item.source: item for item in catalog.sources}
    requests: list[PluginInstallRequest] = []
    blockers: list[PluginInstallBlocker] = []
    if not plan.python_compatible:
        blockers.append(PluginInstallBlocker(None, "python-incompatible"))
    if not plan.wagent_compatible:
        blockers.append(PluginInstallBlocker(None, "wagent-incompatible"))

    for resolution in plan.plugins:
        if resolution.action is CompositionPluginAction.USE_INSTALLED:
            continue
        requirement = resolution.requirement
        if resolution.action not in {
            CompositionPluginAction.INSTALL,
            CompositionPluginAction.CHANGE_VERSION,
        }:
            blockers.append(
                PluginInstallBlocker(requirement.name, resolution.action.value)
            )
            continue
        if requirement.source is None:
            blockers.append(PluginInstallBlocker(requirement.name, "source-unselected"))
            continue
        index = indexes.get(requirement.source)
        if index is None:
            blockers.append(PluginInstallBlocker(requirement.name, "source-unavailable"))
            continue
        specifier = SpecifierSet(requirement.version)
        matching = [
            item
            for item in catalog.plugins
            if item.name == requirement.name
            and item.source == requirement.source
            and specifier.contains(Version(item.version), prereleases=True)
        ]
        if not matching:
            blockers.append(PluginInstallBlocker(requirement.name, "lock-unavailable"))
            continue
        selected_version = max(Version(item.version) for item in matching)
        selected = next(
            item for item in matching if Version(item.version) == selected_version
        )
        requests.append(PluginInstallRequest(plan.digest, selected, index))

    return PluginInstallationPlan(plan.digest, tuple(requests), tuple(blockers))


def plugin_installation_plan_to_dict(
    plan: PluginInstallationPlan,
) -> dict[str, object]:
    """Return a credential-free review projection with only index origins."""

    return {
        "composition_digest": plan.composition_digest,
        "installable": plan.installable,
        "requests": [
            {
                "request_digest": item.digest,
                "plugin": item.lock.name,
                "version": item.lock.version,
                "source": item.lock.source,
                "index_origin": item.index.origin,
                "insecure_transport": item.index.url.startswith("http://"),
                "entry": item.lock.entry,
                "packages": [
                    {
                        "name": package.name,
                        "version": package.version,
                        "sha256": list(package.sha256),
                    }
                    for package in item.lock.packages
                ],
                "network_required": True,
                "package_code_execution": True,
                "plugin_load_authorized": False,
            }
            for item in plan.requests
        ],
        "blockers": [
            {"plugin": item.plugin_name, "reason": item.reason}
            for item in plan.blockers
        ],
    }


def load_plugin_install_catalog(path: str | Path) -> PluginInstallCatalog:
    """Load a strict JSON package-lock catalog without imports or I/O beyond disk."""

    source = Path(path)
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise CompositionError("plugin install catalog is not valid JSON") from error
    if not isinstance(data, dict) or set(data) != {
        "schema_version",
        "sources",
        "plugins",
    }:
        raise CompositionError("plugin install catalog root is invalid")
    if data["schema_version"] != 1:
        raise CompositionError("unsupported plugin install catalog schema version")
    if not isinstance(data["sources"], list) or not isinstance(data["plugins"], list):
        raise CompositionError("plugin install catalog collections must be lists")

    sources: list[PackageIndex] = []
    for index, row in enumerate(data["sources"]):
        if not isinstance(row, dict) or not set(row).issubset(
            {"source", "url", "allow_insecure"}
        ):
            raise CompositionError(f"sources[{index}] is malformed")
        try:
            sources.append(PackageIndex(**row))
        except TypeError as error:
            raise CompositionError(f"sources[{index}] is malformed") from error

    locks: list[PluginPackageLock] = []
    for index, row in enumerate(data["plugins"]):
        if not isinstance(row, dict) or set(row) != {
            "name",
            "version",
            "source",
            "entry",
            "packages",
        }:
            raise CompositionError(f"plugins[{index}] is malformed")
        package_rows = row["packages"]
        if not isinstance(package_rows, list):
            raise CompositionError(f"plugins[{index}].packages must be a list")
        packages: list[LockedPackage] = []
        for package_index, package in enumerate(package_rows):
            if not isinstance(package, dict) or set(package) != {
                "name",
                "version",
                "sha256",
            }:
                raise CompositionError(
                    f"plugins[{index}].packages[{package_index}] is malformed"
                )
            if not isinstance(package["sha256"], list):
                raise CompositionError(
                    f"plugins[{index}].packages[{package_index}].sha256 must be a list"
                )
            try:
                packages.append(
                    LockedPackage(
                        package["name"],
                        package["version"],
                        tuple(package["sha256"]),
                    )
                )
            except TypeError as error:
                raise CompositionError(
                    f"plugins[{index}].packages[{package_index}] is malformed"
                ) from error
        locks.append(
            PluginPackageLock(
                row["name"],
                row["version"],
                row["source"],
                row["entry"],
                tuple(packages),
            )
        )
    return PluginInstallCatalog(tuple(sources), tuple(locks))


def recommended_docker_install_user() -> str | None:
    """Map writable bind mounts to the host user where POSIX IDs are available.

    Docker Desktop on Windows does not expose POSIX host IDs; returning ``None``
    selects the image user (normally container root) while the provider still
    applies a read-only root filesystem, dropped capabilities, no-new-privileges,
    and only the explicitly selected writable workspace mount.
    """

    getuid = getattr(os, "getuid", None)
    getgid = getattr(os, "getgid", None)
    if callable(getuid) and callable(getgid):
        return f"{getuid()}:{getgid()}"
    return None


@dataclass(frozen=True, slots=True, init=False)
class PluginInstallAuthorization:
    """Runtime-only proof of the exact reviewed package-install request."""

    request_digest: str
    source: str

    def __init__(self, request_digest: str, source: str, sentinel: object) -> None:
        if sentinel is not _AUTHORIZATION_SENTINEL:
            raise PermissionError("use PluginInstallAuthorization.grant()")
        object.__setattr__(self, "request_digest", request_digest)
        object.__setattr__(self, "source", source)

    @classmethod
    def grant(
        cls,
        request_digest: str,
        source: str,
        *,
        acknowledge_network_access: bool,
        acknowledge_package_code: bool,
    ) -> PluginInstallAuthorization:
        if not isinstance(request_digest, str) or not _SHA256.fullmatch(request_digest):
            raise ValueError("plugin install request digest is invalid")
        if not isinstance(source, str) or not source.strip():
            raise ValueError("plugin install authorization source must not be empty")
        if (
            acknowledge_network_access is not True
            or acknowledge_package_code is not True
        ):
            raise PermissionError(
                "plugin installation requires network and package-code acknowledgement"
            )
        return cls(request_digest, source.strip(), _AUTHORIZATION_SENTINEL)


@dataclass(frozen=True, slots=True)
class PluginInstallResult:
    """Verified local plugin site produced by one exact request."""

    request_digest: str
    composition_digest: str
    plugin_name: str
    plugin_version: str
    source: str
    entry: str
    target: Path
    tree_digest: str
    packages: tuple[LockedPackage, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.request_digest, str)
            or not isinstance(self.composition_digest, str)
            or not _SHA256.fullmatch(self.request_digest)
            or not _SHA256.fullmatch(self.composition_digest)
        ):
            raise PluginInstallationError("plugin installation identity is invalid")
        if not isinstance(self.tree_digest, str) or not _SHA256.fullmatch(
            self.tree_digest
        ):
            raise PluginInstallationError("plugin installation tree digest is invalid")
        PluginRequirement(self.plugin_name, source=self.source)
        try:
            Version(self.plugin_version)
        except (InvalidVersion, TypeError) as error:
            raise PluginInstallationError(
                "plugin installation version is invalid"
            ) from error
        PluginReference(self.entry)
        if not self.packages or not all(
            isinstance(item, LockedPackage) for item in self.packages
        ):
            raise PluginInstallationError("plugin installation packages are invalid")
        object.__setattr__(self, "target", Path(self.target).resolve())
        object.__setattr__(self, "packages", tuple(self.packages))


class PackageInstaller(Protocol):
    async def install(
        self,
        request: PluginInstallRequest,
        authorization: PluginInstallAuthorization,
        *,
        cancellation: CancellationToken | None = None,
    ) -> PluginInstallResult: ...


class SandboxPipPackageInstaller:
    """Install a fully locked wheel closure through a selected SandboxProvider."""

    def __init__(
        self,
        provider: SandboxProvider,
        sandbox: SandboxSpec,
        *,
        python_executable: str = "python",
        target_root: str = ".wagent/plugins",
        timeout: float = 300,
        max_output_bytes: int = 1_048_576,
    ) -> None:
        relative = PurePosixPath(target_root)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError("plugin install target root must be a safe relative path")
        if not python_executable.strip() or "\0" in python_executable:
            raise ValueError("plugin installer Python executable is invalid")
        if timeout <= 0 or max_output_bytes <= 0:
            raise ValueError("plugin installer limits must be positive")
        if sandbox.workspace_access is not WorkspaceAccess.READ_WRITE:
            raise ValueError("plugin installation needs a writable sandbox workspace")
        if sandbox.network is not SandboxNetwork.BRIDGE:
            raise ValueError("plugin installation needs explicit sandbox network access")
        self.provider = provider
        self.sandbox = sandbox
        self.python_executable = python_executable
        self.target_root = relative
        self.timeout = timeout
        self.max_output_bytes = max_output_bytes

    async def install(
        self,
        request: PluginInstallRequest,
        authorization: PluginInstallAuthorization,
        *,
        cancellation: CancellationToken | None = None,
    ) -> PluginInstallResult:
        if not isinstance(authorization, PluginInstallAuthorization):
            raise PermissionError("plugin installation needs explicit authorization")
        if authorization.request_digest != request.digest:
            raise PermissionError("plugin install authorization does not match request")
        workspace = self.sandbox.workspace
        relative_target = self.target_root / request.lock.name / request.lock.version
        relative_target = relative_target / request.digest[:16]
        target = (workspace / Path(*relative_target.parts)).resolve()
        _require_child(workspace, target)
        if target.exists():
            raise PluginInstallationError("plugin install target already exists")
        created_parents: list[Path] = []
        parent = target.parent
        while parent != workspace and not parent.exists():
            created_parents.append(parent)
            parent = parent.parent
        requirements = "\n".join(
            item.requirement_line() for item in request.lock.packages
        ) + "\n"
        stage = Path(tempfile.mkdtemp(prefix=".wagent-plugin-stage-", dir=workspace))
        site = stage / "site"
        requirements_path = stage / "requirements.txt"
        handle = None
        succeeded = False
        target_created = False
        try:
            site.mkdir()
            with requirements_path.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(requirements)
            handle = await self.provider.open(
                replace(self.sandbox, workspace=stage),
                cancellation=cancellation,
            )
            result = await handle.execute(
                SandboxCommand(
                    (
                        self.python_executable,
                        "-m",
                        "pip",
                        "--isolated",
                        "install",
                        "--no-input",
                        "--disable-pip-version-check",
                        "--no-cache-dir",
                        "--no-compile",
                        "--require-hashes",
                        "--only-binary=:all:",
                        "--no-deps",
                        "--target",
                        "site",
                        "--index-url",
                        request.index.url,
                        "-r",
                        requirements_path.name,
                    ),
                    timeout=self.timeout,
                    max_output_bytes=self.max_output_bytes,
                ),
                cancellation=cancellation,
            )
            if result.exit_code != 0:
                raise PluginInstallationError(
                    f"sandbox package installation failed with status {result.exit_code}"
                )
            await handle.close()
            handle = None
            tree_digest = _tree_digest(site)
            target.mkdir(parents=True, exist_ok=False)
            target_created = True
            shutil.copytree(site, target, symlinks=True, dirs_exist_ok=True)
            if _tree_digest(target) != tree_digest:
                raise PluginInstallationError(
                    "plugin install tree changed during promotion"
                )
            provenance = {
                "schema_version": 1,
                "request_digest": request.digest,
                "composition_digest": request.composition_digest,
                "plugin": {
                    "name": request.lock.name,
                    "version": request.lock.version,
                    "source": request.lock.source,
                    "entry": request.lock.entry,
                },
                "packages": [
                    {
                        "name": item.name,
                        "version": item.version,
                        "sha256": list(item.sha256),
                    }
                    for item in request.lock.packages
                ],
                "tree_digest": tree_digest,
            }
            _atomic_write(
                target / _PROVENANCE_FILE,
                json.dumps(
                    provenance,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8"),
            )
            installed = PluginInstallResult(
                request.digest,
                request.composition_digest,
                request.lock.name,
                request.lock.version,
                request.lock.source,
                request.lock.entry,
                target,
                tree_digest,
                request.lock.packages,
            )
            shutil.rmtree(stage)
            succeeded = True
            return installed
        except PluginInstallationError:
            raise
        except Exception:
            raise PluginInstallationError(
                "sandbox package installation failed"
            ) from None
        finally:
            close_error: BaseException | None = None
            if handle is not None:
                try:
                    await handle.close()
                except BaseException as error:  # fail closed on uncertain sandbox cleanup
                    close_error = error
            if (not succeeded or close_error is not None) and target_created:
                shutil.rmtree(target, ignore_errors=True)
            if not succeeded or close_error is not None:
                for parent in created_parents:
                    try:
                        parent.rmdir()
                    except OSError:
                        break
            shutil.rmtree(stage, ignore_errors=True)
            if close_error is not None:
                raise PluginInstallationError(
                    "plugin installation sandbox cleanup failed"
                ) from None


@dataclass(frozen=True, slots=True)
class InstalledPluginReference:
    """A verified install result plus host-owned runtime configuration."""

    installation: PluginInstallResult
    config: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.installation, PluginInstallResult):
            raise PluginInstallationError(
                "installed plugin reference needs a verified install result"
            )
        object.__setattr__(self, "config", MappingProxyType(dict(self.config)))


class InstalledPluginBatch:
    """Own loaded plugin handles and process import-path leases."""

    def __init__(self, handles: Iterable[PluginHandle], paths: Iterable[Path]) -> None:
        self.handles = tuple(handles)
        self.paths = tuple(paths)
        self._closed = False

    async def unload(self) -> None:
        if self._closed:
            return
        self._closed = True
        failures: list[BaseException] = []
        for handle in reversed(self.handles):
            try:
                await handle.unload()
            except BaseException as error:
                failures.append(error)
        for path in reversed(self.paths):
            _release_import_path(path)
        if failures:
            error = PluginLoadError("installed plugin batch unload failed")
            error.add_note(f"{len(failures)} unload operation(s) failed")
            raise error from failures[0]

    async def __aenter__(self) -> InstalledPluginBatch:
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        await self.unload()


async def load_installed_plugin_references(
    manager: PluginManager,
    references: Iterable[InstalledPluginReference],
) -> InstalledPluginBatch:
    """Verify installed trees, lease their paths, then use normal plugin loading.

    Calling this function is the independent plugin-code loading boundary.  A
    UI or host must obtain a second confirmation after package installation.
    """

    values = tuple(references)
    installations = {item.installation.entry: item.installation for item in values}
    paths: list[Path] = []
    plugin_references: list[PluginReference] = []

    def verify_before_setup(reference: PluginReference, plugin: Plugin) -> None:
        installation = installations[reference.entry]
        module_name = installation.entry.split(":", 1)[0]
        module = sys.modules.get(module_name)
        module_file = getattr(module, "__file__", None)
        if (
            not isinstance(module_file, str)
            or not Path(module_file).resolve().is_relative_to(installation.target)
        ):
            raise PluginInstallationError(
                "installed plugin entry resolved outside the verified site"
            )
        if (
            plugin.spec.name != installation.plugin_name
            or Version(plugin.spec.version) != Version(installation.plugin_version)
        ):
            raise PluginInstallationError(
                "installed plugin identity does not match the reviewed lock"
            )

    try:
        for item in values:
            installation = item.installation
            if _tree_digest(installation.target) != installation.tree_digest:
                raise PluginInstallationError("installed plugin tree changed after install")
            module_name = installation.entry.split(":", 1)[0]
            module_parts = module_name.split(".")
            for depth in range(1, len(module_parts) + 1):
                cached_name = ".".join(module_parts[:depth])
                if cached_name in sys.modules:
                    raise PluginInstallationError(
                        "installed plugin entry is already loaded; use a fresh process"
                    )
            _acquire_import_path(installation.target)
            paths.append(installation.target)
            plugin_references.append(
                PluginReference(installation.entry, item.config, enabled=True)
            )
        handles = await load_plugin_references(
            manager,
            plugin_references,
            pre_load_validator=verify_before_setup,
        )
    except BaseException:
        for path in reversed(paths):
            _release_import_path(path)
        raise
    return InstalledPluginBatch(handles, paths)


def load_plugin_install_result(path: str | Path) -> PluginInstallResult:
    """Re-open and verify a persisted installation without importing its code."""

    target = Path(path).resolve()
    provenance_path = target / _PROVENANCE_FILE
    try:
        data = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PluginInstallationError("plugin install provenance is unavailable") from error
    if not isinstance(data, dict) or set(data) != {
        "schema_version",
        "request_digest",
        "composition_digest",
        "plugin",
        "packages",
        "tree_digest",
    }:
        raise PluginInstallationError("plugin install provenance is malformed")
    if data["schema_version"] != 1 or not isinstance(data["plugin"], dict):
        raise PluginInstallationError("plugin install provenance version is unsupported")
    if set(data["plugin"]) != {"name", "version", "source", "entry"}:
        raise PluginInstallationError("plugin install provenance plugin is malformed")
    if not isinstance(data["packages"], list):
        raise PluginInstallationError("plugin install provenance packages are malformed")
    packages: list[LockedPackage] = []
    try:
        for package in data["packages"]:
            if not isinstance(package, dict) or set(package) != {
                "name",
                "version",
                "sha256",
            }:
                raise PluginInstallationError(
                    "plugin install provenance package is malformed"
                )
            packages.append(
                LockedPackage(
                    package["name"],
                    package["version"],
                    tuple(package["sha256"]),
                )
            )
        result = PluginInstallResult(
            data["request_digest"],
            data["composition_digest"],
            data["plugin"]["name"],
            data["plugin"]["version"],
            data["plugin"]["source"],
            data["plugin"]["entry"],
            target,
            data["tree_digest"],
            tuple(packages),
        )
    except (KeyError, TypeError, CompositionError) as error:
        raise PluginInstallationError("plugin install provenance is malformed") from error
    if _tree_digest(target) != result.tree_digest:
        raise PluginInstallationError("installed plugin tree digest mismatch")
    return result


def _tree_digest(root: Path) -> str:
    if not root.is_dir():
        raise PluginInstallationError("installed plugin target is unavailable")
    digest = hashlib.sha256()
    paths = sorted(
        root.rglob("*"),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    for path in paths:
        relative_path = path.relative_to(root)
        if path.is_symlink():
            raise PluginInstallationError("installed plugin tree contains a symlink")
        if "__pycache__" in relative_path.parts or path.suffix in {".pyc", ".pyo"}:
            raise PluginInstallationError(
                "installed plugin tree contains executable bytecode"
            )
        if relative_path.as_posix() == _PROVENANCE_FILE:
            continue
        if path.is_dir():
            continue
        if not path.is_file():
            raise PluginInstallationError("installed plugin tree contains a special file")
        relative = relative_path.as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    return digest.hexdigest()


def _require_child(root: Path, target: Path) -> None:
    root = root.resolve()
    try:
        target.relative_to(root)
    except ValueError as error:
        raise PluginInstallationError("plugin install path escapes workspace") from error
    if target == root:
        raise PluginInstallationError("plugin install path cannot be workspace root")


def _atomic_write(path: Path, payload: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


_IMPORT_PATH_LOCK = threading.Lock()
_IMPORT_PATH_REFS: dict[str, int] = {}
_IMPORT_PATH_OWNED: set[str] = set()


def _acquire_import_path(path: Path) -> None:
    value = str(path.resolve())
    with _IMPORT_PATH_LOCK:
        count = _IMPORT_PATH_REFS.get(value, 0)
        if count == 0 and value not in sys.path:
            sys.path.insert(0, value)
            _IMPORT_PATH_OWNED.add(value)
        _IMPORT_PATH_REFS[value] = count + 1


def _release_import_path(path: Path) -> None:
    value = str(path.resolve())
    with _IMPORT_PATH_LOCK:
        count = _IMPORT_PATH_REFS.get(value, 0)
        if count <= 1:
            _IMPORT_PATH_REFS.pop(value, None)
            if value in _IMPORT_PATH_OWNED:
                _IMPORT_PATH_OWNED.remove(value)
                try:
                    sys.path.remove(value)
                except ValueError:
                    pass
        else:
            _IMPORT_PATH_REFS[value] = count - 1
