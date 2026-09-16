"""Safe endpoint and opt-in active model-provider probes."""

from __future__ import annotations

import asyncio
import inspect
import socket
import ssl
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import IntEnum, StrEnum
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from .errors import ModelError, ModelFailureKind
from .provider import CancellationToken, ModelProvider
from .types import (
    MessageRole,
    ModelCapability,
    ModelMessage,
    ModelRequest,
    collect_stream,
)


class ProbeMode(StrEnum):
    """Probe intensity. Active and capability modes may incur provider cost."""

    SAFE = "safe"
    ACTIVE = "active"
    CAPABILITY = "capability"


class ProbeLevel(IntEnum):
    L1_REACHABILITY = 1
    L2_AUTHENTICATION = 2
    L3_CATALOG = 3
    L4_GENERATION = 4
    L5_STREAMING = 5
    L6_TOOLS_STRUCTURED = 6
    L7_MULTIMODAL = 7


class ProbeStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class ProbeCheck:
    """One independently explainable probe observation."""

    level: ProbeLevel
    name: str
    status: ProbeStatus
    message: str
    latency_ms: float | None = None
    failure_kind: ModelFailureKind | None = None
    capabilities: frozenset[ModelCapability] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """Versioned, expiring probe result safe for health and routing plugins."""

    target: str
    mode: ProbeMode
    checks: tuple[ProbeCheck, ...]
    started_at: datetime
    completed_at: datetime
    expires_at: datetime
    probe_version: str = "1"

    @property
    def successful(self) -> bool:
        """Return false only when at least one performed check failed."""

        return not any(check.status == ProbeStatus.FAIL for check in self.checks)

    @property
    def latency_ms(self) -> float:
        """Return end-to-end wall-clock probe latency."""

        return max(0.0, (self.completed_at - self.started_at).total_seconds() * 1000)


class EndpointProbe:
    """Perform L1 URL, DNS, TCP, TLS, and HTTP reachability checks."""

    def __init__(self, *, timeout: float = 3.0, ttl: timedelta = timedelta(minutes=5)):
        if timeout <= 0:
            raise ValueError("probe timeout must be positive")
        self.timeout = timeout
        self.ttl = ttl

    async def probe(self, endpoint: str) -> ProbeResult:
        """Probe an HTTP(S) endpoint without sending credentials or body data."""

        started = datetime.now(UTC)
        checks = await asyncio.to_thread(self._probe_sync, endpoint)
        completed = datetime.now(UTC)
        return ProbeResult(
            target=_redact_endpoint(endpoint),
            mode=ProbeMode.SAFE,
            checks=checks,
            started_at=started,
            completed_at=completed,
            expires_at=completed + self.ttl,
        )

    def _probe_sync(self, endpoint: str) -> tuple[ProbeCheck, ...]:
        checks: list[ProbeCheck] = []
        try:
            parsed = urlsplit(endpoint)
            hostname = parsed.hostname
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except ValueError:
            parsed = None
            hostname = None
            port = None
        if (
            parsed is None
            or parsed.scheme not in {"http", "https"}
            or not hostname
            or port is None
        ):
            return (
                ProbeCheck(
                    ProbeLevel.L1_REACHABILITY,
                    "url",
                    ProbeStatus.FAIL,
                    "endpoint must be an absolute HTTP(S) URL",
                    failure_kind=ModelFailureKind.CONFIGURATION,
                ),
            )
        checks.append(
            ProbeCheck(
                ProbeLevel.L1_REACHABILITY,
                "url",
                ProbeStatus.PASS,
                "valid absolute HTTP(S) URL",
            )
        )
        started = time.perf_counter()
        try:
            addresses = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        except OSError as exc:
            checks.append(
                _failed_network_check("dns", exc, started, ModelFailureKind.NETWORK)
            )
            return tuple(checks)
        checks.append(
            _passed_check("dns", f"resolved {len(addresses)} address(es)", started)
        )

        started = time.perf_counter()
        try:
            connection = socket.create_connection((hostname, port), self.timeout)
        except (OSError, TimeoutError) as exc:
            kind = (
                ModelFailureKind.TIMEOUT
                if isinstance(exc, TimeoutError)
                else ModelFailureKind.NETWORK
            )
            checks.append(_failed_network_check("tcp", exc, started, kind))
            return tuple(checks)
        checks.append(_passed_check("tcp", f"connected to port {port}", started))

        if parsed.scheme == "https":
            started = time.perf_counter()
            try:
                context = ssl.create_default_context()
                with context.wrap_socket(
                    connection, server_hostname=hostname
                ) as secured:
                    secured.do_handshake()
            except (OSError, ssl.SSLError, TimeoutError) as exc:
                connection.close()
                checks.append(
                    _failed_network_check(
                        "tls", exc, started, ModelFailureKind.PROTOCOL
                    )
                )
                return tuple(checks)
            checks.append(_passed_check("tls", "TLS handshake succeeded", started))
        else:
            connection.close()

        started = time.perf_counter()
        request = Request(
            _redact_endpoint(endpoint),
            method="HEAD",
            headers={"User-Agent": "W-Agent-Probe/1"},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                status = response.status
        except HTTPError as exc:
            status = exc.code
        except (URLError, OSError, TimeoutError) as exc:
            reason = exc.reason if isinstance(exc, URLError) else exc
            kind = (
                ModelFailureKind.TIMEOUT
                if isinstance(reason, TimeoutError)
                else ModelFailureKind.NETWORK
            )
            checks.append(_failed_network_check("http", reason, started, kind))
            return tuple(checks)
        checks.append(
            _passed_check("http", f"HTTP endpoint responded with {status}", started)
        )
        return tuple(checks)


class ModelProviderProbe:
    """Probe provider catalog safely and generation only with explicit opt-in."""

    def __init__(self, *, ttl: timedelta = timedelta(minutes=5)) -> None:
        self.ttl = ttl

    async def probe(
        self,
        name: str,
        provider: ModelProvider,
        *,
        mode: ProbeMode = ProbeMode.SAFE,
        allow_active: bool = False,
        model: str | None = None,
        cancellation: CancellationToken | None = None,
    ) -> ProbeResult:
        """Inspect a provider, keeping all potentially billed calls opt-in."""

        started = datetime.now(UTC)
        checks: list[ProbeCheck] = []
        descriptors = ()
        catalog_started = time.perf_counter()
        try:
            descriptors = await provider.list_models()
        except ModelError as exc:
            checks.extend(
                (
                    ProbeCheck(
                        ProbeLevel.L2_AUTHENTICATION,
                        "provider-access",
                        ProbeStatus.FAIL,
                        exc.failure.message,
                        _elapsed_ms(catalog_started),
                        exc.failure.kind,
                    ),
                    ProbeCheck(
                        ProbeLevel.L3_CATALOG,
                        "model-catalog",
                        ProbeStatus.SKIPPED,
                        "catalog unavailable because provider access failed",
                    ),
                )
            )
        except Exception as exc:
            checks.extend(
                (
                    ProbeCheck(
                        ProbeLevel.L2_AUTHENTICATION,
                        "provider-access",
                        ProbeStatus.FAIL,
                        str(exc),
                        _elapsed_ms(catalog_started),
                        ModelFailureKind.PROVIDER,
                    ),
                    ProbeCheck(
                        ProbeLevel.L3_CATALOG,
                        "model-catalog",
                        ProbeStatus.SKIPPED,
                        "catalog unavailable because provider access failed",
                    ),
                )
            )
        else:
            latency = _elapsed_ms(catalog_started)
            checks.append(
                ProbeCheck(
                    ProbeLevel.L2_AUTHENTICATION,
                    "provider-access",
                    ProbeStatus.PASS,
                    "provider accepted the catalog request",
                    latency,
                )
            )
            checks.append(
                ProbeCheck(
                    ProbeLevel.L3_CATALOG,
                    "model-catalog",
                    ProbeStatus.PASS,
                    f"provider returned {len(descriptors)} model(s)",
                    latency,
                    capabilities=frozenset(
                        capability
                        for descriptor in descriptors
                        for capability in descriptor.capabilities
                    ),
                )
            )

        if mode != ProbeMode.SAFE:
            if not allow_active:
                checks.append(
                    ProbeCheck(
                        ProbeLevel.L4_GENERATION,
                        "active-generation",
                        ProbeStatus.SKIPPED,
                        "active probe requires allow_active=True and may incur cost",
                    )
                )
            elif descriptors:
                selected = (
                    next(
                        (
                            descriptor
                            for descriptor in descriptors
                            if descriptor.model == model
                        ),
                        None,
                    )
                    if model is not None
                    else descriptors[0]
                )
                if selected is None:
                    checks.append(
                        ProbeCheck(
                            ProbeLevel.L4_GENERATION,
                            "active-generation",
                            ProbeStatus.FAIL,
                            f"requested probe model {model!r} is not in the catalog",
                            failure_kind=ModelFailureKind.CONFIGURATION,
                        )
                    )
                else:
                    checks.extend(
                        await self._active_probe(provider, selected.model, cancellation)
                    )

        if mode == ProbeMode.CAPABILITY:
            declared = frozenset(
                capability
                for descriptor in descriptors
                for capability in descriptor.capabilities
            )
            checks.extend(self._capability_checks(declared, allow_active))

        completed = datetime.now(UTC)
        return ProbeResult(
            target=name,
            mode=mode,
            checks=tuple(checks),
            started_at=started,
            completed_at=completed,
            expires_at=completed + self.ttl,
        )

    async def _active_probe(
        self,
        provider: ModelProvider,
        model: str,
        cancellation: CancellationToken | None,
    ) -> tuple[ProbeCheck, ...]:
        started = time.perf_counter()
        request = ModelRequest(
            model=model,
            messages=(ModelMessage.text(MessageRole.USER, "Reply with OK."),),
            max_output_tokens=8,
        )
        try:
            response = await collect_stream(
                provider.stream(request, cancellation=cancellation)
            )
        except ModelError as exc:
            return (
                ProbeCheck(
                    ProbeLevel.L4_GENERATION,
                    "active-generation",
                    ProbeStatus.FAIL,
                    exc.failure.message,
                    _elapsed_ms(started),
                    exc.failure.kind,
                ),
            )
        except Exception as exc:
            return (
                ProbeCheck(
                    ProbeLevel.L4_GENERATION,
                    "active-generation",
                    ProbeStatus.FAIL,
                    str(exc),
                    _elapsed_ms(started),
                    ModelFailureKind.PROTOCOL,
                ),
            )
        latency = _elapsed_ms(started)
        return (
            ProbeCheck(
                ProbeLevel.L4_GENERATION,
                "active-generation",
                ProbeStatus.PASS,
                f"generation completed with {response.finish_reason.value}",
                latency,
            ),
            ProbeCheck(
                ProbeLevel.L5_STREAMING,
                "stream-protocol",
                ProbeStatus.PASS,
                "stream contained a valid terminal event",
                latency,
                capabilities=frozenset({ModelCapability.STREAMING}),
            ),
        )

    @staticmethod
    def _capability_checks(
        declared: frozenset[ModelCapability], allow_active: bool
    ) -> tuple[ProbeCheck, ...]:
        groups = (
            (
                ProbeLevel.L6_TOOLS_STRUCTURED,
                "tools-structured",
                {ModelCapability.TOOL_CALLING, ModelCapability.STRUCTURED_OUTPUT},
            ),
            (
                ProbeLevel.L7_MULTIMODAL,
                "multimodal",
                {
                    ModelCapability.IMAGE_INPUT,
                    ModelCapability.IMAGE_OUTPUT,
                    ModelCapability.AUDIO_INPUT,
                    ModelCapability.AUDIO_OUTPUT,
                },
            ),
        )
        checks = []
        for level, name, capabilities in groups:
            present = declared & capabilities
            message = "provider declares: " + (
                ", ".join(sorted(item.value for item in present)) or "none"
            )
            if allow_active:
                message += "; no provider-specific active verifier is installed"
            checks.append(
                ProbeCheck(
                    level,
                    name,
                    ProbeStatus.SKIPPED,
                    message,
                    capabilities=frozenset(present),
                )
            )
        return tuple(checks)


class ProbeCache:
    """Small in-memory cache that never treats expired results as current."""

    def __init__(self) -> None:
        self._results: dict[str, ProbeResult] = {}

    def put(self, result: ProbeResult) -> None:
        self._results[result.target] = result

    def get(self, target: str, *, now: datetime | None = None) -> ProbeResult | None:
        result = self._results.get(target)
        current = now or datetime.now(UTC)
        if result is None or result.expires_at <= current:
            return None
        return result


class PeriodicProbeService:
    """Run any caller-supplied probe periodically without editing configuration."""

    def __init__(
        self,
        probe: Callable[[], Awaitable[ProbeResult]],
        *,
        interval: float,
        on_result: Callable[[ProbeResult], Any] | None = None,
    ) -> None:
        if interval <= 0:
            raise ValueError("probe interval must be positive")
        self.probe = probe
        self.interval = interval
        self.on_result = on_result
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        """Start one background loop in the current event loop."""

        if self.running:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Stop the loop idempotently and wait for cleanup."""

        self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            result = await self.probe()
            if self.on_result is not None:
                outcome = self.on_result(result)
                if inspect.isawaitable(outcome):
                    await outcome
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval)
            except TimeoutError:
                continue


def _redact_endpoint(endpoint: str) -> str:
    try:
        parsed = urlsplit(endpoint)
        host = parsed.hostname or ""
        port = parsed.port
    except ValueError:
        return "invalid-endpoint"
    if port is not None:
        host = f"{host}:{port}"
    return urlunsplit((parsed.scheme, host, parsed.path, "", ""))


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


def _passed_check(name: str, message: str, started: float) -> ProbeCheck:
    return ProbeCheck(
        ProbeLevel.L1_REACHABILITY,
        name,
        ProbeStatus.PASS,
        message,
        _elapsed_ms(started),
    )


def _failed_network_check(
    name: str,
    error: object,
    started: float,
    kind: ModelFailureKind,
) -> ProbeCheck:
    return ProbeCheck(
        ProbeLevel.L1_REACHABILITY,
        name,
        ProbeStatus.FAIL,
        str(error),
        _elapsed_ms(started),
        kind,
    )
