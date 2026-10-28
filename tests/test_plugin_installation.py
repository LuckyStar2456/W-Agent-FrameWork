import json
import sys
from pathlib import Path

import pytest

from w_agent import (
    CompositionEnvironment,
    CompositionError,
    CompositionManifest,
    PackageIndex,
    PluginInstallAuthorization,
    PluginInstallCatalog,
    PluginInstallationError,
    PluginManager,
    PluginPackageLock,
    PluginRequirement,
    PluginState,
    SandboxNetwork,
    SandboxPipPackageInstaller,
    SandboxResult,
    SandboxSpec,
    StaticCompositionDependencyResolver,
    InstalledPluginReference,
    LockedPackage,
    load_installed_plugin_references,
    load_plugin_install_catalog,
    load_plugin_install_result,
    plan_composition,
    plan_plugin_installations,
    plugin_installation_plan_to_dict,
    recommended_docker_install_user,
)


HASH = "a" * 64


def _dependency_plan(*, source="pypi"):
    manifest = CompositionManifest(
        "portable-stack",
        "1.0.0",
        requires_wagent=">=2.0.0a1,<3",
        plugins=(PluginRequirement("demo-plugin", ">=1,<2", source),),
    )
    return plan_composition(
        manifest,
        CompositionEnvironment("3.11.9", "2.0.0a3"),
        StaticCompositionDependencyResolver(),
    )


def _catalog():
    return PluginInstallCatalog(
        (PackageIndex("pypi", "https://packages.example/simple"),),
        (
            PluginPackageLock(
                "demo-plugin",
                "1.2.0",
                "pypi",
                "demo_plugin:setup",
                (LockedPackage("demo-distribution", "1.2.0", (HASH,)),),
            ),
        ),
    )


def test_install_plan_resolves_exact_lock_without_network_or_imports():
    module_name = "demo_plugin"
    sys.modules.pop(module_name, None)

    install_plan = plan_plugin_installations(_dependency_plan(), _catalog())
    payload = plugin_installation_plan_to_dict(install_plan)

    assert install_plan.installable is True
    assert len(install_plan.requests) == 1
    assert install_plan.requests[0].lock.version == "1.2.0"
    assert payload["requests"][0]["network_required"] is True
    assert payload["requests"][0]["plugin_load_authorized"] is False
    assert payload["requests"][0]["index_origin"] == "https://packages.example"
    assert "/simple" not in json.dumps(payload)
    assert module_name not in sys.modules


def test_install_plan_reports_source_and_lock_blockers():
    unavailable_source = plan_plugin_installations(
        _dependency_plan(),
        PluginInstallCatalog((), _catalog().plugins),
    )
    missing_source = plan_plugin_installations(
        _dependency_plan(source=None),
        _catalog(),
    )

    assert unavailable_source.blockers[0].reason == "source-unavailable"
    assert missing_source.blockers[0].reason == "select-source"


def test_install_catalog_is_strict_and_rejects_embedded_credentials(tmp_path):
    catalog = tmp_path / "install-lock.json"
    catalog.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "sources": [
                    {
                        "source": "pypi",
                        "url": "https://packages.example/simple",
                    }
                ],
                "plugins": [
                    {
                        "name": "demo-plugin",
                        "version": "1.2.0",
                        "source": "pypi",
                        "entry": "demo_plugin:setup",
                        "packages": [
                            {
                                "name": "demo-distribution",
                                "version": "1.2.0",
                                "sha256": [HASH],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    loaded = load_plugin_install_catalog(catalog)
    assert loaded.plugins[0].packages[0].canonical_name == "demo-distribution"

    data = json.loads(catalog.read_text(encoding="utf-8"))
    data["sources"][0]["url"] = "https://user:secret@packages.example/simple"
    catalog.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(CompositionError, match="credentials"):
        load_plugin_install_catalog(catalog)


class _FakeHandle:
    def __init__(
        self,
        workspace: Path,
        *,
        status: int = 0,
        execution_error: Exception | None = None,
    ) -> None:
        self.workspace = workspace
        self.status = status
        self.execution_error = execution_error
        self.commands = []
        self.requirements = None
        self.closed = False

    async def execute(self, command, *, cancellation=None):
        self.commands.append((command, cancellation))
        if self.execution_error is not None:
            raise self.execution_error
        argv = command.argv
        requirement_path = self.workspace / argv[argv.index("-r") + 1]
        self.requirements = requirement_path.read_text(encoding="utf-8")
        target = self.workspace / Path(argv[argv.index("--target") + 1])
        if self.status == 0:
            target.joinpath("demo_plugin.py").write_text(
                "from w_agent import plugin\n"
                "@plugin(name='demo-plugin', version='1.2.0')\n"
                "async def setup(context):\n"
                "    context.config.get('mode')\n",
                encoding="utf-8",
            )
        return SandboxResult(self.status, "potential package output", "secret error")

    async def close(self):
        self.closed = True


class _FakeProvider:
    def __init__(
        self,
        workspace: Path,
        *,
        status: int = 0,
        execution_error: Exception | None = None,
    ) -> None:
        self.handle = _FakeHandle(
            workspace,
            status=status,
            execution_error=execution_error,
        )
        self.opens = []

    async def open(self, spec, *, cancellation=None):
        self.opens.append((spec, cancellation))
        self.handle.workspace = spec.workspace
        return self.handle


def _installer(tmp_path, *, status=0, execution_error=None):
    provider = _FakeProvider(
        tmp_path,
        status=status,
        execution_error=execution_error,
    )
    installer = SandboxPipPackageInstaller(
        provider,
        SandboxSpec(tmp_path, network=SandboxNetwork.BRIDGE),
    )
    return provider, installer


def _authorization(request):
    return PluginInstallAuthorization.grant(
        request.digest,
        "pytest",
        acknowledge_network_access=True,
        acknowledge_package_code=True,
    )


@pytest.mark.asyncio
async def test_sandbox_installer_uses_locked_wheels_and_persists_provenance(tmp_path):
    request = plan_plugin_installations(_dependency_plan(), _catalog()).requests[0]
    provider, installer = _installer(tmp_path)

    result = await installer.install(request, _authorization(request))
    command = provider.handle.commands[0][0].argv

    assert "--isolated" in command
    assert "--require-hashes" in command
    assert "--only-binary=:all:" in command
    assert "--no-deps" in command
    assert provider.handle.requirements == (
        f"demo-distribution==1.2.0 --hash=sha256:{HASH}\n"
    )
    assert provider.handle.closed is True
    assert provider.opens[0][0].workspace != tmp_path
    assert provider.opens[0][0].workspace.parent == tmp_path
    assert not provider.opens[0][0].workspace.exists()
    assert not list(tmp_path.glob(".wagent-plugin-stage-*"))
    assert load_plugin_install_result(result.target) == result


@pytest.mark.asyncio
async def test_installer_binds_authorization_and_cleans_failed_target(tmp_path):
    request = plan_plugin_installations(_dependency_plan(), _catalog()).requests[0]
    provider, installer = _installer(tmp_path, status=2)
    wrong = PluginInstallAuthorization.grant(
        "b" * 64,
        "pytest",
        acknowledge_network_access=True,
        acknowledge_package_code=True,
    )

    with pytest.raises(PermissionError, match="does not match"):
        await installer.install(request, wrong)
    with pytest.raises(PluginInstallationError, match="status 2"):
        await installer.install(request, _authorization(request))

    assert provider.handle.closed is True
    assert not (tmp_path / ".wagent" / "plugins").exists()


@pytest.mark.asyncio
async def test_installer_mounts_only_fresh_stage_and_preserves_workspace_file(tmp_path):
    request = plan_plugin_installations(_dependency_plan(), _catalog()).requests[0]
    provider, installer = _installer(tmp_path)
    existing = tmp_path / "session-state.json"
    existing.write_text("user-owned", encoding="utf-8")

    await installer.install(request, _authorization(request))

    assert existing.read_text(encoding="utf-8") == "user-owned"
    assert provider.opens[0][0].workspace != tmp_path
    assert not provider.opens[0][0].workspace.exists()


@pytest.mark.asyncio
async def test_installer_closes_and_cleans_after_uncertain_execution_error(tmp_path):
    request = plan_plugin_installations(_dependency_plan(), _catalog()).requests[0]
    provider, installer = _installer(
        tmp_path,
        execution_error=RuntimeError("SECRET_SANDBOX_FAILURE"),
    )

    with pytest.raises(PluginInstallationError, match="installation failed") as caught:
        await installer.install(request, _authorization(request))

    assert "SECRET_SANDBOX_FAILURE" not in str(caught.value)
    assert provider.handle.closed is True
    assert not (tmp_path / ".wagent" / "plugins").exists()


@pytest.mark.asyncio
async def test_verified_install_loads_through_normal_plugin_lifecycle(tmp_path):
    request = plan_plugin_installations(_dependency_plan(), _catalog()).requests[0]
    _provider, installer = _installer(tmp_path)
    result = await installer.install(request, _authorization(request))
    manager = PluginManager()
    original_path = tuple(sys.path)
    sys.modules.pop("demo_plugin", None)

    batch = await load_installed_plugin_references(
        manager,
        (InstalledPluginReference(result, {"mode": "safe"}),),
    )

    assert manager.record("demo-plugin").state is PluginState.ACTIVE
    assert str(result.target) in sys.path
    await batch.unload()
    assert manager.record("demo-plugin").state is PluginState.DISPOSED
    assert tuple(sys.path) == original_path
    sys.modules.pop("demo_plugin", None)


@pytest.mark.asyncio
async def test_installed_tree_tampering_fails_before_plugin_import(tmp_path):
    request = plan_plugin_installations(_dependency_plan(), _catalog()).requests[0]
    _provider, installer = _installer(tmp_path)
    result = await installer.install(request, _authorization(request))
    result.target.joinpath("demo_plugin.py").write_text(
        "raise RuntimeError('must not import')\n",
        encoding="utf-8",
    )
    sys.modules.pop("demo_plugin", None)

    with pytest.raises(PluginInstallationError, match="changed after install"):
        await load_installed_plugin_references(
            PluginManager(),
            (InstalledPluginReference(result),),
        )
    assert "demo_plugin" not in sys.modules


def test_install_authorization_requires_both_acknowledgements():
    with pytest.raises(PermissionError, match="network and package-code"):
        PluginInstallAuthorization.grant(
            "a" * 64,
            "pytest",
            acknowledge_network_access=True,
            acknowledge_package_code=False,
        )
    with pytest.raises(CompositionError, match="insecure"):
        PackageIndex("private", "http://packages.example/simple")
    assert recommended_docker_install_user() is None or ":" in (
        recommended_docker_install_user() or ""
    )
