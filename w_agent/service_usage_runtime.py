"""Explicit named observation bindings and non-budget model attempt observer."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field, replace
from uuid import uuid4

from w_agent.models import (
    CancellationToken, FinishEvent, ModelDescriptor, ModelProvider, ModelRequest,
    ModelStreamValidator, StreamEvent,
)
from w_agent.service_usage import ServiceUsageError, ServiceUsageLedger, ServiceUsageRecord, _label
from w_agent.service_usage_adapters import ServiceUsageMeasurement
from w_agent.service_usage_links import ServiceUsageLinkStore


@dataclass(frozen=True, slots=True)
class LocalServiceUsageConfig:
    """Opaque catalog selection, never authority, path, factory or tenant."""

    binding: str

    def __post_init__(self) -> None:
        _label(self.binding)


@dataclass(frozen=True, slots=True)
class LocalServiceUsageBinding:
    """Borrowed host ledger; one explicit operation may span multiple Runs.

    The ledger observes calls, not permissions or budgets. The optional retrieval
    meter must not count costs already assigned to observed child services.
    """

    ledger: ServiceUsageLedger = field(repr=False)
    operation_id: str
    model_source_ref: str = "model"
    meter_version: str = "runtime-v1"
    retrieval_source_ref: str | None = None
    retrieval_measurement: Callable[[tuple], ServiceUsageMeasurement] | None = field(default=None, repr=False)
    retrieval_token_scope: str = "expected"
    links: ServiceUsageLinkStore | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        for name in ("record", "records"):
            if not callable(getattr(self.ledger, name, None)):
                raise ValueError("service usage binding needs a ledger protocol")
        ServiceUsageRecord(self.operation_id, "validation", "model", self.model_source_ref, self.meter_version)
        if self.retrieval_source_ref is not None:
            ServiceUsageRecord(self.operation_id, "validation", "retrieval", self.retrieval_source_ref,
                               self.meter_version, token_scope=self.retrieval_token_scope)
        elif self.retrieval_measurement is not None:
            raise ValueError("retrieval measurement requires explicit retrieval observation")
        if self.retrieval_token_scope not in {"expected", "not-applicable"}:
            raise ValueError("invalid retrieval token scope")
        if self.retrieval_measurement is not None and not callable(self.retrieval_measurement):
            raise ValueError("retrieval measurement must be callable")
        if self.links is not None and any(not callable(getattr(self.links, name, None))
                                          for name in ("bind", "get", "for_session", "for_operation")):
            raise ValueError("service usage links require a link-store protocol")


@dataclass(frozen=True, slots=True)
class ObservedModelProvider:
    """Observe each actual stream invocation without reserving or pricing it.

    A complete validated stream without Usage is a completed call with unknown
    tokens, never a known zero. Failed/abandoned streams remain unknown. EOF and
    accounting precede Finish delivery. No native cursor forwarding or provider
    ownership: the runtime closes the underlying assembled provider exactly once.
    """

    provider: ModelProvider = field(repr=False)
    binding: LocalServiceUsageBinding = field(repr=False)

    @property
    def catalog_probe_scope(self) -> str:
        return getattr(self.provider, "catalog_probe_scope", "unknown")

    async def list_models(self) -> tuple[ModelDescriptor, ...]:
        return await self.provider.list_models()

    async def resolve(self, model: str) -> ModelDescriptor:
        return await self.provider.resolve(model)

    async def stream(self, request: ModelRequest, *, cancellation: CancellationToken | None = None) -> AsyncIterator[StreamEvent]:
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        binding = self.binding
        started = ServiceUsageRecord(binding.operation_id, uuid4().hex, "model",
                                     binding.model_source_ref, binding.meter_version)
        try:
            await binding.ledger.record(started)
        except asyncio.CancelledError:
            raise
        except Exception:
            raise ServiceUsageError("service-usage-start-failed-provider-not-entered") from None
        source = None
        recorded = False
        entered = False
        try:
            if cancellation is not None:
                cancellation.raise_if_cancelled()
            entered = True  # Stream construction itself may perform external work.
            source = self.provider.stream(request, cancellation=cancellation)
            validator = ModelStreamValidator()
            finish = None
            async for event in source:
                if cancellation is not None:
                    cancellation.raise_if_cancelled()
                validator.feed(event)
                if isinstance(event, FinishEvent):
                    finish = event
                else:
                    yield event
            response = validator.finish()
            closing, source = source, None
            await _close_stream(closing)
            completed = replace(started, status="completed",
                                usage=response.usage if response.usage_reported else None,
                                usage_complete=response.usage_reported)
            try:
                await binding.ledger.record(completed)
            except asyncio.CancelledError:
                raise
            except Exception:
                raise ServiceUsageError("service-usage-completion-record-failed-do-not-replay") from None
            recorded = True
            yield finish
        finally:
            try:
                if source is not None:
                    await _close_stream(source)
            finally:
                if not recorded:
                    try:
                        await binding.ledger.record(replace(started, status="unknown" if entered else "not-incurred"))
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        raise ServiceUsageError("service-usage-unknown-record-failed-do-not-replay") from None


async def _close_stream(stream: object) -> None:
    closer = getattr(stream, "aclose", None)
    if closer is not None:
        try:
            await closer()
        except asyncio.CancelledError:
            raise
        except Exception:
            raise ServiceUsageError("service-usage-stream-close-failed-do-not-replay") from None
