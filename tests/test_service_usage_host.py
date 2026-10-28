"""Explicit usage factory consent, cleanup and safe UI summaries."""

import asyncio
import sys
from types import ModuleType

import pytest

from w_agent._service_usage_ui import ServiceUsageEntryError, ServiceUsageOptions, service_usage_binding_scope, service_usage_summary
from w_agent.service_usage import InMemoryServiceUsageLedger
from w_agent.service_usage_runtime import LocalServiceUsageBinding


@pytest.mark.parametrize("options", [("host:factory", False, False), ("host:factory", True, False),
                                      ("host:factory", False, True), (None, True, True),
                                      ("../bad:factory", True, True), ("host:factory", 1, True)])
def test_pure_options_require_separate_code_and_record_authority(options):
    with pytest.raises(ServiceUsageEntryError):
        ServiceUsageOptions(*options)


@pytest.mark.asyncio
async def test_unapproved_or_unselected_factory_is_never_imported(monkeypatch):
    import w_agent._service_usage_ui as ui
    monkeypatch.setattr(ui.importlib, "import_module", lambda *_: pytest.fail("unauthorized import"))
    for options in ({"confirmed": True}, {"confirm_record": True}, {"confirmed": True, "confirm_record": True, "selected": None}):
        selected = options.pop("selected", "ledger")
        with pytest.raises(ServiceUsageEntryError):
            async with service_usage_binding_scope("host:factory", selected=selected, **options):
                pytest.fail("scope entered")
    with pytest.raises(ServiceUsageEntryError):
        async with service_usage_binding_scope(None, selected="ledger"):
            pytest.fail("selected binding silently ignored")
    async with service_usage_binding_scope(None, selected=None) as result:
        assert dict(result) == {}


def factory_module(monkeypatch, *, invalid=False, fail_cleanup=False, suppress=False):
    events = []
    binding = LocalServiceUsageBinding(InMemoryServiceUsageLedger(), "host-operation")
    class Context:
        async def __aenter__(self):
            events.append("entered")
            return {"ledger": object() if invalid else binding}
        async def __aexit__(self, kind, value, trace):
            events.append(kind)
            if fail_cleanup:
                raise RuntimeError("PRIVATE_CLEANUP")
            return suppress
    module = ModuleType("_usage_test_host")
    module.factory = Context
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return binding, events


@pytest.mark.asyncio
async def test_authorized_factory_catalog_is_borrowed_and_summary_inside_scope(monkeypatch):
    binding, events = factory_module(monkeypatch)
    async with service_usage_binding_scope("_usage_test_host:factory", selected="ledger", confirmed=True, confirm_record=True) as catalog:
        assert catalog["ledger"] is binding
        summary = await service_usage_summary(binding)
        assert summary["scope"] == "host-operation-not-this-run" and summary["records"] == 0
        assert summary["usage_complete"] is False
        assert events == ["entered"]
        with pytest.raises(TypeError):
            catalog["other"] = binding
    assert events == ["entered", None]


@pytest.mark.asyncio
async def test_invalid_catalog_still_exits_factory(monkeypatch):
    _, events = factory_module(monkeypatch, invalid=True)
    with pytest.raises(ServiceUsageEntryError, match="catalog"):
        async with service_usage_binding_scope("_usage_test_host:factory", selected="ledger", confirmed=True, confirm_record=True):
            pytest.fail("invalid catalog accepted")
    assert events == ["entered", ServiceUsageEntryError]


@pytest.mark.asyncio
async def test_host_cannot_suppress_runtime_failure_and_cleanup_does_not_replace_it(monkeypatch):
    for fail_cleanup in (False, True):
        _, events = factory_module(monkeypatch, fail_cleanup=fail_cleanup, suppress=True)
        with pytest.raises(RuntimeError, match="runtime-failed"):
            async with service_usage_binding_scope("_usage_test_host:factory", selected="ledger", confirmed=True, confirm_record=True):
                raise RuntimeError("runtime-failed")
        assert events == ["entered", RuntimeError]


@pytest.mark.asyncio
async def test_cleanup_failure_after_success_warns_no_replay(monkeypatch):
    factory_module(monkeypatch, fail_cleanup=True)
    with pytest.raises(ServiceUsageEntryError, match="do not replay"):
        async with service_usage_binding_scope("_usage_test_host:factory", selected="ledger", confirmed=True, confirm_record=True):
            pass


@pytest.mark.asyncio
async def test_summary_cancellation_propagates():
    class Cancelled(InMemoryServiceUsageLedger):
        async def records(self, operation):
            raise asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await service_usage_summary(LocalServiceUsageBinding(Cancelled(), "operation"))
