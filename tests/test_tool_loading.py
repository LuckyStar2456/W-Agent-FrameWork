import sys
import types

import pytest

from w_agent import ToolEntryLoadError, load_tool_entries, python_tool


def test_explicit_tool_entries_load_bindings_from_factory(monkeypatch):
    module = types.ModuleType("test_local_tool_module")
    called = []

    def factory():
        called.append(True)
        return (python_tool(lambda value: value, name="echo"),)

    module.factory = factory
    monkeypatch.setitem(sys.modules, module.__name__, module)

    catalog = load_tool_entries(("test_local_tool_module:factory",))

    assert list(catalog) == ["echo"]
    assert called == [True]


def test_explicit_tool_entries_reject_invalid_shape_and_duplicates(monkeypatch):
    module = types.ModuleType("test_invalid_tool_module")
    module.invalid = {"not": "bindings"}
    module.first = python_tool(lambda: None, name="same")
    module.second = python_tool(lambda: None, name="same")
    monkeypatch.setitem(sys.modules, module.__name__, module)

    with pytest.raises(ToolEntryLoadError, match="ToolBinding"):
        load_tool_entries(("test_invalid_tool_module:invalid",))
    with pytest.raises(ToolEntryLoadError, match="duplicate"):
        load_tool_entries(
            (
                "test_invalid_tool_module:first",
                "test_invalid_tool_module:second",
            )
        )
