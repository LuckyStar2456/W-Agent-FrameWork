import base64
import zlib

import pytest

from w_agent import (
    CompositionError,
    CompositionManifest,
    CompositionStore,
    PluginRequirement,
    decode_composition,
    encode_composition,
    inspect_composition,
)


def _manifest(version="1.0.0", **kwargs):
    return CompositionManifest(
        "coding-stack",
        version,
        plugins=(PluginRequirement("example-plugin", ">=1,<2", "pypi"),),
        profiles={"default": "coding"},
        policies={"sandbox": {"type": "docker"}},
        **kwargs,
    )


def test_composition_code_is_deterministic_and_preview_only():
    manifest = _manifest()
    code = encode_composition(manifest)

    assert encode_composition(manifest) == code
    assert decode_composition(code) == manifest
    preview = inspect_composition(code)
    assert preview.manifest == manifest
    assert preview.plugin_dependencies == ("example-plugin>=1,<2",)
    assert "third-party-plugins-require-confirmation" in preview.risks


def test_composition_rejects_secrets_paths_unsafe_local_and_corruption():
    with pytest.raises(CompositionError, match="secret"):
        _manifest(routing={"api_key": "secret"})
    with pytest.raises(CompositionError, match="absolute"):
        _manifest(tools={"workspace": "C:\\private\\repo"})
    with pytest.raises(CompositionError, match="secret"):
        _manifest(routing={"auth_token": "secret"})
    with pytest.raises(CompositionError, match="local"):
        PluginRequirement("local", source="file:///private/plugin")
    with pytest.raises(CompositionError, match="credentials"):
        PluginRequirement("private", source="https://user:pass@example.test/pkg")
    with pytest.raises(CompositionError, match="unsafe local"):
        CompositionManifest(
            "unsafe",
            "1.0.0",
            policies={"sandbox": {"type": "unsafe-local"}},
        )

    code = encode_composition(_manifest())
    with pytest.raises(CompositionError, match="checksum"):
        decode_composition(code[:-1] + ("0" if code[-1] != "0" else "1"))

    compressed = zlib.compress(b"x" * (1024 * 1024 + 1), level=9)
    encoded = base64.urlsafe_b64encode(compressed).rstrip(b"=").decode()
    with pytest.raises(CompositionError, match="too large"):
        decode_composition(f"wagent-compose:v1:{encoded}:{'0' * 64}")
    with pytest.raises(CompositionError, match="too large"):
        encode_composition(
            CompositionManifest("large", "1.0.0", description="x" * 1_100_000)
        )


def test_store_versions_aliases_and_refuses_content_conflicts(tmp_path):
    store = CompositionStore(tmp_path)
    first = _manifest()
    second = _manifest("2.0.0")

    store.save(first, alias="stable")
    store.save(second)

    assert store.load("stable") == first
    assert store.load("coding-stack", "2.0.0") == second
    assert store.versions("coding-stack") == ("1.0.0", "2.0.0")

    changed = CompositionManifest(
        "coding-stack",
        "1.0.0",
        description="different",
    )
    with pytest.raises(CompositionError, match="different content"):
        store.save(changed)
    with pytest.raises(CompositionError, match="portable"):
        store.load("..", "1.0.0")


def test_manifest_nested_configuration_is_immutable():
    source = {"agent": {"tools": ["read"]}}
    manifest = CompositionManifest("frozen", "1.0.0", profiles=source)
    source["agent"]["tools"].append("write")

    assert manifest.profiles["agent"]["tools"] == ("read",)
    with pytest.raises(TypeError):
        manifest.profiles["agent"]["new"] = True
