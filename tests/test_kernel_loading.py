from dataclasses import dataclass
import sys
import types

import pytest

from w_agent import (
    PluginReference,
    PluginLoadError,
    PluginManager,
    PluginSpec,
    PluginState,
    discover_entrypoint_plugins,
    load_plugin_references,
    load_yaml_references,
    plugin,
    preview_plugin_references,
)


def test_yaml_loader_parses_without_importing_plugin_code(tmp_path):
    config = tmp_path / "plugins.yml"
    config.write_text(
        """
plugins:
  - entry: example.module:plugin
    enabled: true
    config:
      endpoint: https://example.com/v1
  - entry: example.disabled:plugin
    enabled: false
""".strip(),
        encoding="utf-8",
    )

    references = load_yaml_references(config)

    assert references == (
        PluginReference(
            "example.module:plugin",
            {"endpoint": "https://example.com/v1"},
            True,
        ),
        PluginReference("example.disabled:plugin", {}, False),
    )


def test_yaml_loader_rejects_invalid_rows(tmp_path):
    config = tmp_path / "plugins.yml"
    config.write_text("plugins:\n  - config: {}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="entry must be a string"):
        load_yaml_references(config)


def test_entrypoint_discovery_uses_the_same_decorated_plugin_spec():
    @plugin(name="entry-plugin", version="1.0.0")
    async def setup(_context):
        return None

    @dataclass
    class FakeEntryPoint:
        group: str
        value: object

        def load(self):
            return self.value

    plugins = discover_entrypoint_plugins(
        entry_points=(
            FakeEntryPoint("other", setup),
            FakeEntryPoint("w_agent.plugins", setup),
        )
    )

    assert len(plugins) == 1
    assert plugins[0].spec == PluginSpec(name="entry-plugin", version="1.0.0")


def test_plugin_reference_preview_is_import_free_and_hides_config_values():
    summaries = preview_plugin_references(
        (
            PluginReference(
                "missing.module:plugin",
                {"endpoint": "SECRET_ENDPOINT", "token": "SECRET_TOKEN"},
            ),
            PluginReference("also.missing:plugin", enabled=False),
        )
    )

    assert summaries[0].entry == "missing.module:plugin"
    assert summaries[0].config_keys == ("endpoint", "token")
    assert summaries[1].enabled is False
    assert "SECRET_ENDPOINT" not in repr(summaries)
    assert "SECRET_TOKEN" not in repr(summaries)


@pytest.mark.asyncio
async def test_explicit_plugin_batch_loads_enabled_entries_and_passes_config(
    monkeypatch,
):
    module = types.ModuleType("test_plugin_batch_module")
    seen = []

    @plugin(name="batch-one", version="1.0.0")
    async def setup(context):
        seen.append(dict(context.config))

    module.setup = setup
    monkeypatch.setitem(sys.modules, module.__name__, module)
    manager = PluginManager()

    handles = await load_plugin_references(
        manager,
        (
            PluginReference(
                "test_plugin_batch_module:setup",
                {"mode": "safe"},
            ),
            PluginReference("not.imported:plugin", enabled=False),
        ),
    )

    assert [handle.name for handle in handles] == ["batch-one"]
    assert manager.record("batch-one").state == PluginState.ACTIVE
    assert seen == [{"mode": "safe"}]
    await manager.close()
    assert manager.record("batch-one").state == PluginState.DISPOSED


@pytest.mark.asyncio
async def test_plugin_batch_failure_rolls_back_plugins_loaded_by_batch(monkeypatch):
    module = types.ModuleType("test_plugin_rollback_module")
    lifecycle = []

    @plugin(name="batch-good", version="1.0.0")
    async def good(context):
        lifecycle.append("loaded")
        return lambda: lifecycle.append("disposed")

    @plugin(name="batch-bad", version="1.0.0")
    async def bad(_context):
        raise RuntimeError("SECRET_PLUGIN_FAILURE")

    module.good = good
    module.bad = bad
    monkeypatch.setitem(sys.modules, module.__name__, module)
    manager = PluginManager()

    with pytest.raises(PluginLoadError, match="batch failed") as caught:
        await load_plugin_references(
            manager,
            (
                PluginReference("test_plugin_rollback_module:good"),
                PluginReference("test_plugin_rollback_module:bad"),
            ),
        )

    assert manager.record("batch-good").state == PluginState.DISPOSED
    assert lifecycle == ["loaded", "disposed"]
    assert "SECRET_PLUGIN_FAILURE" not in str(caught.value)


@pytest.mark.parametrize("entry", ["missing-colon", ":plugin", "module:", "a:b:c"])
def test_plugin_reference_requires_exact_entry_syntax(entry):
    with pytest.raises(ValueError, match="module:attribute|required"):
        PluginReference(entry)
