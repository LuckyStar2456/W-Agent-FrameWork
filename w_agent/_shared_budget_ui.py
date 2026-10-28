"""Explicit host-code loading and body-free budget display for CLI/TUI.

Factories are trusted local Python, not sandboxed plugins or model tools.
"""

from __future__ import annotations

import importlib
import inspect
import re
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from types import MappingProxyType
from typing import Any

from w_agent.local_runtime import LocalSharedBudgetBinding, LocalSharedBudgetConfig


class BudgetEntryError(ValueError):
    """Fixed-message host lifecycle failure; never authorize model replay."""


@asynccontextmanager
async def budget_binding_scope(
    entry: str | None, *, selected: str | None, confirmed: bool = False,
) -> AsyncIterator[Mapping[str, LocalSharedBudgetBinding]]:
    """Open a zero-argument async context-manager factory after explicit consent.

    The host context owns initialization/cleanup; its exit return value cannot
    suppress a Runtime exception. Imports are never inferred from configuration.
    """
    if entry is None:
        yield MappingProxyType({})
        return
    if confirmed is not True:
        raise BudgetEntryError("budget code not authorized; explicitly confirm host Python execution")
    if selected is None:
        raise BudgetEntryError("budget entry requires a shared_budget.binding selection in configuration")
    if (not isinstance(entry, str) or len(entry) > 512
            or not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*", entry, flags=re.ASCII)):
        raise BudgetEntryError("budget entry must be an explicit module:factory reference")
    try:
        module, name = entry.split(":")
        factory = getattr(importlib.import_module(module), name)
        context = factory()
        if inspect.iscoroutine(context):
            context.close()
            raise ValueError("factory must return an async context manager, not a coroutine")
        if not callable(getattr(context, "__aenter__", None)) or not callable(getattr(context, "__aexit__", None)):
            raise ValueError("async context manager required")
        catalog = await context.__aenter__()
    except Exception:
        raise BudgetEntryError("budget host setup failed; inspect state before retrying; no automatic model replay") from None
    try:
        try:
            if not isinstance(catalog, Mapping) or not 1 <= len(catalog) <= 64:
                raise ValueError("bounded binding catalog required")
            bindings = dict(catalog)
            for key, value in bindings.items():
                LocalSharedBudgetConfig(key)
                if not isinstance(value, LocalSharedBudgetBinding):
                    raise ValueError("typed budget binding required")
            if selected not in bindings:
                raise ValueError("selected binding absent")
        except Exception:
            raise BudgetEntryError("budget host returned an invalid catalog or missing selection") from None
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
        raise BudgetEntryError("budget host cleanup failed; inspect state; do not replay the model call") from None


async def shared_budget_summary(binding: LocalSharedBudgetBinding | None) -> dict[str, Any] | None:
    """Pool totals only; never disclose reservation IDs, evidence or actor labels.

    A read failure after generation is a display warning, not a failed Run or
    permission to rerun it. Cancellation still propagates.
    """
    if binding is None:
        return None
    try:
        view = await binding.snapshot()
        counts = {status: 0 for status in ("pending", "unknown", "settled", "released")}
        for entry in view.entries:
            counts[entry.status] += 1
        limits = view.limits
        return {
            "status": "available", "scope": "shared-pool-not-this-run",
            "known_usage": _usage(view.known_usage), "held_usage": _usage(view.held_usage),
            "known_cost": None if view.known_cost is None else str(view.known_cost),
            "held_cost": None if view.held_cost is None else str(view.held_cost),
            "currency": limits.currency,
            "limits": {
                "input_tokens": limits.max_input_tokens, "output_tokens": limits.max_output_tokens,
                "total_tokens": limits.max_total_tokens,
                "cost": None if limits.max_cost is None else str(limits.max_cost),
            },
            "tickets": counts, "blocked": view.blocked, "breached": view.breached,
        }
    except Exception:
        return {"status": "unavailable", "scope": "shared-pool-not-this-run",
                "message": "Budget display unavailable; Run outcome is unchanged. Inspect ledger; do not replay."}


def _usage(usage: Any) -> dict[str, int]:
    return {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
            "cached_input_tokens": usage.cached_input_tokens, "total_tokens": usage.total_tokens}
