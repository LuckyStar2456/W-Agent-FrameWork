"""Host-owned 1.x singleton borrowing without duplicate lifecycle ownership."""

from collections.abc import Mapping

from w_agent.container.bean_factory import BeanFactory

from .planning import AssemblyDefinitionError, BorrowedComponent, ComponentRef


def borrow_legacy_singletons(
    factory: BeanFactory, names: Mapping[str, str],
) -> tuple[BorrowedComponent, ...]:
    """Map application identities to existing legacy singleton names.

    Call after host initialization. Close applications before destroying the
    legacy factory. This adapter neither starts nor closes the old container;
    its existing failure/initialization semantics are not upgraded by borrowing.
    """
    if not isinstance(factory, BeanFactory):
        raise TypeError("legacy adapter requires BeanFactory")
    if not isinstance(names, Mapping):
        raise AssemblyDefinitionError("legacy names must be a mapping")
    pairs = tuple(names.items())
    for name, legacy_name in pairs:
        ComponentRef(name)
        ComponentRef(legacy_name)
    return tuple(
        BorrowedComponent(name, factory.existing_singleton(legacy_name))
        for name, legacy_name in pairs
    )
