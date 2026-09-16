from dataclasses import dataclass

import pytest

from w_agent import (
    PluginReference,
    PluginSpec,
    discover_entrypoint_plugins,
    load_yaml_references,
    plugin,
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
