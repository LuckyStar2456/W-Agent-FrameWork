import json
import sys

import pytest

from w_agent import (
    CompositionEnvironment,
    CompositionError,
    CompositionManifest,
    CompositionPluginAction,
    PluginCandidate,
    PluginRequirement,
    StaticCompositionDependencyResolver,
    composition_plan_to_dict,
    load_plugin_candidates,
    plan_composition,
)


def test_offline_plan_selects_highest_compatible_candidate_without_imports():
    module_name = "composition_plan_must_not_import"
    manifest = CompositionManifest(
        "coding-stack",
        "1.0.0",
        requires_python=">=3.11,<3.13",
        requires_wagent=">=2.0.0a1,<3",
        plugins=(
            PluginRequirement("router", ">=1,<2", "pypi"),
        ),
    )
    resolver = StaticCompositionDependencyResolver(
        (
            PluginCandidate("router", "1.2.0", "pypi", f"{module_name}:old"),
            PluginCandidate("router", "1.9.0", "pypi", f"{module_name}:new"),
            PluginCandidate("router", "2.0.0", "pypi", f"{module_name}:next"),
        )
    )

    plan = plan_composition(
        manifest,
        CompositionEnvironment("3.11.9", "2.0.0a3"),
        resolver,
    )

    assert plan.ready is True
    assert plan.load_confirmation_required is True
    assert plan.plugins[0].action is CompositionPluginAction.USE_INSTALLED
    assert plan.plugins[0].candidate.version == "1.9.0"
    assert module_name not in sys.modules


def test_plan_distinguishes_install_source_version_and_ambiguity_actions():
    requirements = (
        PluginRequirement("missing-known", ">=1", "pypi"),
        PluginRequirement("missing-source", ">=1"),
        PluginRequirement("wrong-version", ">=2", "pypi"),
        PluginRequirement("wrong-source", ">=1", "pypi"),
        PluginRequirement("ambiguous", "==1", "pypi"),
    )
    resolver = StaticCompositionDependencyResolver(
        (
            PluginCandidate("wrong-version", "1.0.0", "pypi"),
            PluginCandidate("wrong-source", "1.0.0", "private-index"),
            PluginCandidate("ambiguous", "1.0.0", "pypi", "a:setup"),
            PluginCandidate("ambiguous", "1.0.0", "pypi", "b:setup"),
        )
    )

    plan = plan_composition(
        CompositionManifest(
            "stack",
            "1.0.0",
            requires_wagent=">=2.0.0a1,<3",
            plugins=requirements,
        ),
        CompositionEnvironment("3.11.9", "2.0.0a3"),
        resolver,
    )

    assert [item.action for item in plan.plugins] == [
        CompositionPluginAction.INSTALL,
        CompositionPluginAction.SELECT_SOURCE,
        CompositionPluginAction.CHANGE_VERSION,
        CompositionPluginAction.REVIEW_SOURCE,
        CompositionPluginAction.SELECT_CANDIDATE,
    ]
    assert plan.ready is False


def test_plan_fails_readiness_on_environment_constraints():
    plan = plan_composition(
        CompositionManifest(
            "future",
            "1.0.0",
            requires_python=">=3.13",
            requires_wagent=">=3",
        ),
        CompositionEnvironment("3.11.9", "2.0.0a3"),
    )

    assert plan.python_compatible is False
    assert plan.wagent_compatible is False
    assert plan.ready is False


def test_plugin_candidate_inventory_is_strict_and_import_free(tmp_path):
    module_name = "inventory_must_not_import"
    source = tmp_path / "inventory.json"
    source.write_text(
        json.dumps(
            {
                "plugins": [
                    {
                        "name": "router",
                        "version": "1.0.0",
                        "source": "pypi",
                        "entry": f"{module_name}:setup",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    candidates = load_plugin_candidates(source)

    assert candidates == (
        PluginCandidate("router", "1.0.0", "pypi", f"{module_name}:setup"),
    )
    assert module_name not in sys.modules

    source.write_text(
        json.dumps({"plugins": [], "unexpected": True}),
        encoding="utf-8",
    )
    with pytest.raises(CompositionError, match="only 'plugins'"):
        load_plugin_candidates(source)

    source.write_text(
        json.dumps({"plugins": [{"name": "router", "version": 1}]}),
        encoding="utf-8",
    )
    with pytest.raises(CompositionError, match="must be strings"):
        load_plugin_candidates(source)


def test_plan_projection_contains_no_manifest_configuration_values():
    plan = plan_composition(
        CompositionManifest(
            "private-config",
            "1.0.0",
            requires_wagent=">=2.0.0a1,<3",
            plugins=(PluginRequirement("router", ">=1", "pypi"),),
            routing={"credential_ref": "SECRET_ENV_NAME"},
        ),
        CompositionEnvironment("3.11.9", "2.0.0a3"),
    )

    payload = composition_plan_to_dict(plan)

    assert payload["plugins"][0]["action"] == "install"
    assert "SECRET_ENV_NAME" not in json.dumps(payload)
