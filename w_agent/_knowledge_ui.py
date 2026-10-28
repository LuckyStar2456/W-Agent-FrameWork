"""Explicit CLI/TUI knowledge host lifecycle, separate from retrieval consent."""

from __future__ import annotations

import importlib
import inspect
import re
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from w_agent.knowledge_context import _text
from w_agent.knowledge_runtime import LocalKnowledgeBinding, LocalKnowledgeConfig


class KnowledgeEntryError(ValueError):
    """Fixed host-code lifecycle error; never imply a query/model retry is safe."""


@dataclass(frozen=True, slots=True)
class KnowledgeRunOptions:
    """Pure UI preflight before loading input files, tools or factory code."""

    entry: str | None = field(default=None, repr=False)
    query: str | None = field(default=None, repr=False)
    confirm_code: bool = False
    confirm_query: bool = False

    def __post_init__(self) -> None:
        if any(type(value) is not bool for value in (self.confirm_code, self.confirm_query)):
            raise KnowledgeEntryError("knowledge confirmations must be booleans")
        if self.entry is None and self.query is None:
            if self.confirm_code or self.confirm_query:
                raise KnowledgeEntryError("knowledge confirmation needs an entry and query")
            return
        if (not isinstance(self.entry, str) or len(self.entry) > 512
                or not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*", self.entry, flags=re.ASCII)):
            raise KnowledgeEntryError("knowledge query requires an explicit module:factory entry")
        if self.confirm_code is not True:
            raise KnowledgeEntryError("knowledge host code needs --confirm-knowledge-code / LOAD KNOWLEDGE")
        if self.confirm_query is not True:
            raise KnowledgeEntryError("knowledge query needs --confirm-knowledge-query / QUERY KNOWLEDGE")
        try:
            _text(self.query, 4096)
        except Exception:
            raise KnowledgeEntryError("knowledge query must be nonblank text within 4096 UTF-8 bytes") from None

    def runtime_options(self) -> dict[str, object]:
        if self.query is None:
            return {}
        return {"knowledge_query": self.query, "confirm_knowledge_query": self.confirm_query}


@dataclass(frozen=True, slots=True)
class KnowledgeEvaluationOptions:
    """Authorize one host catalog and retrieval for every bounded case prompt.

    Dataset metadata never supplies entries, grants or retrieval query overrides.
    Frontends preflight the entire dataset before loading host/tool code.
    """

    entry: str | None = field(default=None, repr=False)
    confirm_code: bool = False
    confirm_queries: bool = False

    def __post_init__(self) -> None:
        if any(type(value) is not bool for value in (self.confirm_code, self.confirm_queries)):
            raise KnowledgeEntryError("knowledge evaluation confirmations must be booleans")
        if self.entry is None:
            if self.confirm_code or self.confirm_queries:
                raise KnowledgeEntryError("knowledge evaluation confirmation requires an entry")
            return
        if (not isinstance(self.entry, str) or len(self.entry) > 512
                or not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*", self.entry, flags=re.ASCII)):
            raise KnowledgeEntryError("knowledge evaluation requires a module:factory entry")
        if not self.confirm_code or not self.confirm_queries:
            raise KnowledgeEntryError("knowledge evaluation requires separate host-code and all-case query consent")

    def validate_queries(self, queries: Sequence[str]) -> None:
        if self.entry is None:
            return
        if not queries or len(queries) > 10_000:
            raise KnowledgeEntryError("knowledge evaluation needs a bounded nonempty dataset")
        for query in queries:
            self.runtime_options(query)

    def runtime_options(self, query: str) -> dict[str, object]:
        if self.entry is None:
            return {}
        try:
            _text(query, 4096)
        except Exception:
            raise KnowledgeEntryError("each knowledge evaluation prompt must be nonblank and at most 4096 UTF-8 bytes") from None
        return {"knowledge_query": query, "confirm_knowledge_query": True, "include_history": False}


@asynccontextmanager
async def knowledge_binding_scope(options: KnowledgeRunOptions | KnowledgeEvaluationOptions, *, selected: str | None) -> AsyncIterator[Mapping[str, LocalKnowledgeBinding]]:
    """Borrow an explicitly authorized async factory context for one invocation.

    Factories own all initialization/cleanup. Their __aexit__ return value cannot
    suppress a Runtime exception. Configuration alone never imports host code.
    """
    if not isinstance(options, (KnowledgeRunOptions, KnowledgeEvaluationOptions)):
        raise KnowledgeEntryError("typed knowledge options are required")
    if options.entry is None:
        yield MappingProxyType({})
        return
    if selected is None:
        raise KnowledgeEntryError("knowledge entry requires knowledge.binding in configuration")
    try:
        LocalKnowledgeConfig(selected)
        module, name = options.entry.split(":")
        factory = getattr(importlib.import_module(module), name)
        context = factory()
        if inspect.iscoroutine(context):
            context.close()
            raise ValueError("async context manager factory required, not coroutine")
        if any(not callable(getattr(context, method, None)) for method in ("__aenter__", "__aexit__")):
            raise ValueError("async context manager required")
        catalog = await context.__aenter__()
    except Exception:
        raise KnowledgeEntryError("knowledge host setup failed; inspect state before retrying") from None
    try:
        try:
            if not isinstance(catalog, Mapping) or not 1 <= len(catalog) <= 64:
                raise ValueError("bounded knowledge catalog required")
            bindings = dict(catalog)
            for name, binding in bindings.items():
                LocalKnowledgeConfig(name)
                if not isinstance(binding, LocalKnowledgeBinding):
                    raise ValueError("typed knowledge binding required")
            if selected not in bindings:
                raise ValueError("selected knowledge binding is missing")
        except Exception:
            raise KnowledgeEntryError("knowledge host returned an invalid catalog or missing selection") from None
        yield MappingProxyType(bindings)
    except BaseException as error:
        await _exit_context(context, type(error), error, error.__traceback__)
        raise
    else:
        await _exit_context(context, None, None, None)


async def _exit_context(context: Any, *exc_info: Any) -> None:
    try:
        await context.__aexit__(*exc_info)
    except Exception:
        raise KnowledgeEntryError("knowledge host cleanup failed; inspect state; do not replay queries or model calls") from None
