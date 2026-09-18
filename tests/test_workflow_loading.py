import sys
import types

import pytest

from w_agent import (
    PythonWorkflowDefinition,
    WorkflowEntryLoadError,
    load_workflow_entries,
)


def test_explicit_workflow_entries_load_definitions_from_factory(monkeypatch):
    module = types.ModuleType("test_local_workflow_module")
    called = []

    def factory():
        called.append(True)
        return (
            PythonWorkflowDefinition("review", lambda context: "done", version="2"),
        )

    module.factory = factory
    monkeypatch.setitem(sys.modules, module.__name__, module)

    catalog = load_workflow_entries(("test_local_workflow_module:factory",))

    assert list(catalog) == [("review", "2")]
    assert called == [True]


def test_explicit_workflow_entries_reject_invalid_shape_and_duplicates(monkeypatch):
    module = types.ModuleType("test_invalid_workflow_module")
    module.invalid = {"not": "definitions"}
    module.first = PythonWorkflowDefinition("same", lambda context: None)
    module.second = PythonWorkflowDefinition("same", lambda context: None)
    monkeypatch.setitem(sys.modules, module.__name__, module)

    with pytest.raises(WorkflowEntryLoadError, match="workflow definitions"):
        load_workflow_entries(("test_invalid_workflow_module:invalid",))
    with pytest.raises(WorkflowEntryLoadError, match="duplicate"):
        load_workflow_entries(
            (
                "test_invalid_workflow_module:first",
                "test_invalid_workflow_module:second",
            )
        )


@pytest.mark.parametrize("entry", ["missing-separator", ":value", "module:"])
def test_explicit_workflow_entries_require_complete_entry_syntax(entry):
    with pytest.raises(WorkflowEntryLoadError, match="module:attribute|required"):
        load_workflow_entries((entry,))
