"""Stable model and routing failure vocabulary."""

from dataclasses import dataclass
from enum import StrEnum


class ModelFailureKind(StrEnum):
    CONFIGURATION = "configuration"
    AUTHENTICATION = "authentication"
    RATE_LIMIT = "rate-limit"
    TIMEOUT = "timeout"
    NETWORK = "network"
    PROTOCOL = "protocol"
    CONTENT_POLICY = "content-policy"
    PROVIDER = "provider"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ModelFailure:
    kind: ModelFailureKind
    code: str
    message: str
    retryable: bool = False
    provider: str | None = None
    model: str | None = None


class ModelError(RuntimeError):
    """Exception carrying a stable normalized model failure."""

    def __init__(self, failure: ModelFailure) -> None:
        super().__init__(failure.message)
        self.failure = failure


class RoutingError(RuntimeError):
    """No route satisfies a model request."""
