import pytest

from w_agent import (
    AmbiguousCapabilityError,
    CapabilityNotFoundError,
    Contribution,
    RegistrationError,
    Registry,
    ScopePath,
)


def test_scope_path_orders_built_in_dimensions_and_supports_custom_dimensions():
    scope = (
        ScopePath.application("app")
        .child("extension", "custom")
        .child("workspace", "repo")
        .child("session", "chat")
    )

    assert str(scope) == (
        "application:app/extension:custom/workspace:repo/session:chat"
    )
    assert scope.parent == ScopePath.from_pairs(
        (("application", "app"), ("extension", "custom"), ("workspace", "repo"))
    )
    assert ScopePath.application("app").is_ancestor_of(scope)

    with pytest.raises(ValueError, match="documented order"):
        ScopePath.application().child("session", "s").child("workspace", "w")

    with pytest.raises(ValueError, match="only once"):
        ScopePath.application().child("workspace", "one").child("workspace", "two")


def test_registry_resolves_nearest_scope_and_disposes_idempotently():
    registry = Registry()
    application = ScopePath.application("app")
    workspace = application.child("workspace", "repo")
    session = workspace.child("session", "chat")

    global_registration = registry.register(
        Contribution("model.router", "global", scope=application, version="1.0.0")
    )
    local_registration = registry.register(
        Contribution("model.router", "local", scope=workspace, version="1.1.0")
    )

    assert registry.resolve("model.router", session) == "local"
    local_registration.dispose()
    local_registration.dispose()
    assert registry.resolve("model.router", session) == "global"

    global_registration.dispose()
    with pytest.raises(CapabilityNotFoundError):
        registry.resolve("model.router", session)


def test_registry_requires_provider_name_when_same_scope_is_ambiguous():
    registry = Registry()
    scope = ScopePath.application()
    registry.register(Contribution("model", "a", name="a", scope=scope, version="1"))
    registry.register(Contribution("model", "b", name="b", scope=scope, version="1"))

    with pytest.raises(AmbiguousCapabilityError):
        registry.resolve("model", scope)
    assert registry.resolve("model", scope, name="b") == "b"


def test_registry_selects_highest_matching_version_and_snapshot_is_stable():
    registry = Registry()
    scope = ScopePath.application()
    old = registry.register(
        Contribution("model", "v1", name="provider", scope=scope, version="1.0.0")
    )
    snapshot = registry.snapshot()
    registry.register(
        Contribution("model", "v2", name="provider", scope=scope, version="2.0.0")
    )

    assert registry.resolve("model", scope) == "v2"
    assert registry.resolve("model", scope, name="provider") == "v2"
    assert registry.resolve("model", scope, name="provider", version="<2") == "v1"
    old.dispose()
    assert snapshot.resolve("model", scope, name="provider") == "v1"


def test_registry_enforces_exact_duplicate_and_exclusive_capabilities():
    registry = Registry()
    scope = ScopePath.application()
    registry.register(Contribution("storage", object(), scope=scope, version="1"))

    with pytest.raises(RegistrationError, match="already supplies"):
        registry.register(Contribution("storage", object(), scope=scope, version="1"))
    with pytest.raises(RegistrationError, match="exclusive"):
        registry.register(
            Contribution(
                "storage",
                object(),
                name="other",
                scope=scope,
                version="1",
                exclusive=True,
            )
        )
