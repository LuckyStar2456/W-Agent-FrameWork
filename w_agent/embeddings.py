"""Replaceable single-text HTTP embeddings with explicit, optional accounting.

Hosts choose endpoints/models and authorize text disclosure. No discovery,
fallback, batching, automatic retry, environment credentials or index writes.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol
from urllib.parse import urlsplit

from w_agent.knowledge_context import _text
from w_agent.knowledge_ingestion import _label
from w_agent.models import TokenUsage
from w_agent.tools.http_adapter import HttpToolRequest, HttpToolResponse, HttpToolTransport, HttpxToolTransport
from w_agent.vector_retrieval import _integer, _reject_constant, _timeout, _unique_object, _vector


class EmbeddingError(RuntimeError):
    """Fixed public error; a failed/cancelled call may still incur provider charges."""

    def __init__(self, code: str, *, may_have_called: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.may_have_called = may_have_called


def _count(value: int) -> int:
    if type(value) is not int or not 0 <= value < 2**63:
        raise ValueError("embedding token count is invalid")
    return value


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    vector: tuple[float, ...] = field(repr=False)
    model: str | None = field(default=None, repr=False)
    usage: TokenUsage | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "vector", _vector(self.vector))
        if self.model is not None:
            _label(self.model)
        if self.usage is not None:
            if not isinstance(self.usage, TokenUsage):
                raise ValueError("embedding usage is invalid")
            for count in (self.usage.input_tokens, self.usage.output_tokens, self.usage.cached_input_tokens):
                _count(count)
            if self.usage.output_tokens != 0 or self.usage.cached_input_tokens > self.usage.input_tokens:
                raise ValueError("embedding usage is invalid")


class AsyncEmbeddingProvider(Protocol):
    """Structured embedding capability, compatible with a separate vector-only API."""

    async def embed_result(self, text: str) -> EmbeddingResult: ...


class HttpEmbeddingMapping(Protocol):
    """Trusted synchronous mapping; cannot change the adapter's endpoint/headers.

    Extensions themselves are arbitrary host code, not sandboxed by this API.
    Keep mappings pure: their hidden external calls are outside transport usage.
    """

    def build_body(self, text: str, *, model: str) -> dict: ...

    def parse_response(self, payload: dict) -> EmbeddingResult: ...


def _path(value: tuple[str | int, ...]) -> None:
    if (not isinstance(value, tuple) or not 1 <= len(value) <= 16
            or any(not ((isinstance(part, str) and 1 <= len(part) <= 128)
                       or (type(part) is int and 0 <= part <= 65536)) for part in value)):
        raise ValueError("embedding field path is invalid")


def _at(payload: object, path: tuple[str | int, ...], *, optional: bool = False) -> object:
    current = payload
    for part in path:
        if isinstance(part, str) and isinstance(current, dict):
            if part not in current and optional:
                return None
            current = current[part]
        elif type(part) is int and isinstance(current, list):
            current = current[part]
        else:
            raise ValueError("embedding response field has wrong shape")
    return current


@dataclass(frozen=True, slots=True)
class JsonEmbeddingMapping:
    """Top-level input/model fields and explicit nested result paths, no eval.

    A missing optional model/usage field stays unknown; malformed values fail.
    Use a custom mapping for batch, non-JSON or service-specific semantics.
    """

    vector_path: tuple[str | int, ...]
    input_field: str = "input"
    model_field: str = "model"
    response_model_path: tuple[str | int, ...] | None = None
    input_tokens_path: tuple[str | int, ...] | None = None
    parameters_json: str = field(default="{}", repr=False)

    def __post_init__(self) -> None:
        _path(self.vector_path)
        for path in (self.response_model_path, self.input_tokens_path):
            if path is not None:
                _path(path)
        for key in (self.input_field, self.model_field):
            _label(key)
        if self.input_field == self.model_field:
            raise ValueError("embedding request fields collide")
        _text(self.parameters_json, 65536)
        parameters = json.loads(self.parameters_json, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        if not isinstance(parameters, dict) or self.input_field in parameters or self.model_field in parameters:
            raise ValueError("embedding parameters cannot replace input or model")
        encoded = json.dumps(parameters, allow_nan=False, separators=(",", ":"))
        object.__setattr__(self, "parameters_json", encoded)

    def build_body(self, text: str, *, model: str) -> dict:
        return {**json.loads(self.parameters_json), self.input_field: text, self.model_field: model}

    def parse_response(self, payload: dict) -> EmbeddingResult:
        vector = _at(payload, self.vector_path)
        if not isinstance(vector, list):
            raise ValueError("embedding vector must be a JSON list")
        model = _at(payload, self.response_model_path, optional=True) if self.response_model_path is not None else None
        count = _at(payload, self.input_tokens_path, optional=True) if self.input_tokens_path is not None else None
        usage = TokenUsage(_count(count), 0) if count is not None else None
        return EmbeddingResult(tuple(vector), model, usage)


@dataclass(frozen=True, slots=True)
class OpenAIEmbeddingMapping:
    """Single input, float encoding; dimensions parameter is explicitly optional."""

    dimensions: int | None = None

    def __post_init__(self) -> None:
        if self.dimensions is not None:
            _integer(self.dimensions, 65536)

    def build_body(self, text: str, *, model: str) -> dict:
        body = {"model": model, "input": text, "encoding_format": "float"}
        if self.dimensions is not None:
            body["dimensions"] = self.dimensions
        return body

    def parse_response(self, payload: dict) -> EmbeddingResult:
        if payload.get("error") is not None:
            raise ValueError("embedding response is unsuccessful")
        data = payload.get("data")
        if (not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict)
                or type(data[0].get("index")) is not int or data[0]["index"] != 0
                or not isinstance(data[0].get("embedding"), list)):
            raise ValueError("embedding response must contain exactly input zero")
        model = payload["model"]
        _label(model)
        usage = None
        if "usage" in payload:
            raw = payload["usage"]
            if not isinstance(raw, dict):
                raise ValueError("embedding usage is invalid")
            count = _count(raw["prompt_tokens"])
            if _count(raw["total_tokens"]) != count:
                raise ValueError("embedding usage totals disagree")
            usage = TokenUsage(count, 0)
        return EmbeddingResult(tuple(data[0]["embedding"]), model, usage)


@dataclass(frozen=True, slots=True)
class OllamaEmbeddingMapping:
    """Native /api/embed with truncation disabled, not legacy /api/embeddings."""

    dimensions: int | None = None

    def __post_init__(self) -> None:
        if self.dimensions is not None:
            _integer(self.dimensions, 65536)

    def build_body(self, text: str, *, model: str) -> dict:
        body = {"model": model, "input": text, "truncate": False}
        if self.dimensions is not None:
            body["dimensions"] = self.dimensions
        return body

    def parse_response(self, payload: dict) -> EmbeddingResult:
        if payload.get("error") is not None:
            raise ValueError("embedding response is unsuccessful")
        vectors = payload.get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != 1 or not isinstance(vectors[0], list):
            raise ValueError("embedding response must contain one vector")
        model = payload["model"]
        _label(model)
        usage = TokenUsage(_count(payload["prompt_eval_count"]), 0) if "prompt_eval_count" in payload else None
        return EmbeddingResult(tuple(vectors[0]), model, usage)


@dataclass(frozen=True, slots=True)
class HttpTextEmbedder:
    """Fixed-endpoint JSON POST using a borrowed bounded HTTP tool transport.

    embed_result exposes metadata; embed supplies AsyncTextEmbedder compatibility.
    Neither method reserves budgets unless explicitly wrapped by the host.
    """

    endpoint: str = field(repr=False)
    model: str = field(repr=False)
    dimensions: int
    mapping: HttpEmbeddingMapping = field(repr=False)
    headers: Mapping[str, str] = field(default_factory=dict, repr=False)
    transport: HttpToolTransport | None = field(default=None, repr=False)
    timeout: float = 30.0
    max_input_bytes: int = 1024 * 1024
    max_request_bytes: int = 2 * 1024 * 1024
    max_response_bytes: int = 2 * 1024 * 1024
    expected_response_model: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        _label(self.model)
        _integer(self.dimensions, 65536)
        _timeout(self.timeout)
        _integer(self.max_input_bytes, 1024 * 1024)
        _integer(self.max_request_bytes, 16 * 1024 * 1024)
        _integer(self.max_response_bytes, 16 * 1024 * 1024)
        if self.expected_response_model is not None:
            _label(self.expected_response_model)
        try:
            if (not isinstance(self.endpoint, str) or len(self.endpoint) > 4096
                    or any(ord(char) <= 32 or ord(char) == 127 for char in self.endpoint)):
                raise ValueError
            parsed = urlsplit(self.endpoint)
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                    or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment):
                raise ValueError
            _ = parsed.port
        except ValueError:
            raise ValueError("embedding endpoint is invalid") from None
        if any(not callable(getattr(self.mapping, method, None)) for method in ("build_body", "parse_response")):
            raise ValueError("embedding mapping is invalid")
        if not isinstance(self.headers, Mapping) or len(self.headers) > 32:
            raise ValueError("embedding headers are invalid")
        headers: dict[str, str] = {}
        for name, value in self.headers.items():
            if (not isinstance(name, str) or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,128}", name)
                    or not isinstance(value, str) or len(value) > 4096
                    or any(not 32 <= ord(char) <= 126 for char in value)
                    or name.lower() in headers or name.lower() in {"host", "content-length", "transfer-encoding"}):
                raise ValueError("embedding header is invalid")
            headers[name.lower()] = value
        if "content-type" in headers and headers["content-type"].lower() != "application/json":
            raise ValueError("embedding content type must be JSON")
        headers["content-type"] = "application/json"
        object.__setattr__(self, "headers", MappingProxyType(headers))
        transport = self.transport if self.transport is not None else HttpxToolTransport(timeout=self.timeout)
        if not callable(getattr(transport, "send", None)):
            raise ValueError("embedding transport requires send")
        object.__setattr__(self, "transport", transport)

    async def embed(self, text: str) -> tuple[float, ...]:
        return (await self.embed_result(text)).vector

    async def embed_result(self, text: str) -> EmbeddingResult:
        started = False
        try:
            _text(text, self.max_input_bytes)
            body = self.mapping.build_body(text, model=self.model)
            if not isinstance(body, dict):
                raise ValueError("embedding request body is invalid")
            encoded = json.dumps(body, allow_nan=False)
            if len(encoded.encode("utf-8")) > self.max_request_bytes:
                raise ValueError("embedding request exceeds limit")
            # Detach from mutable mapping-owned objects before awaiting transport.
            request = HttpToolRequest("POST", self.endpoint, headers=self.headers,
                                      json_body=json.loads(encoded), max_response_bytes=self.max_response_bytes)
            async with asyncio.timeout(self.timeout):
                started = True
                response = await self.transport.send(request)
            if (not isinstance(response, HttpToolResponse) or type(response.status) is not int or not 200 <= response.status < 300
                    or len(response.body) > self.max_response_bytes):
                raise ValueError("embedding response is invalid")
            payload = json.loads(response.body.decode("utf-8"), object_pairs_hook=_unique_object,
                                 parse_constant=_reject_constant)
            if not isinstance(payload, dict):
                raise ValueError("embedding response must be a JSON object")
            result = self.mapping.parse_response(payload)
            if (not isinstance(result, EmbeddingResult) or len(result.vector) != self.dimensions
                    or (self.expected_response_model is not None and result.model != self.expected_response_model)):
                raise ValueError("embedding result does not match expected identity")
            return result
        except Exception:
            raise EmbeddingError("embedding-call-failed", may_have_called=started) from None


def openai_compatible_text_embedder(base_url: str, model: str, dimensions: int, *,
                                   api_key: str | None = None, request_dimensions: bool = False,
                                   **options) -> HttpTextEmbedder:
    """base_url includes the API prefix, e.g. https://api.openai.com/v1."""
    if type(request_dimensions) is not bool:
        raise ValueError("embedding dimension request switch must be boolean")
    if api_key is not None:
        if not isinstance(api_key, str) or not api_key or any(not 33 <= ord(char) <= 126 for char in api_key):
            raise ValueError("embedding credential is invalid")
        headers = dict(options.pop("headers", {}))
        if any(name.lower() == "authorization" for name in headers):
            raise ValueError("embedding authorization cannot be specified twice")
        options["headers"] = {**headers, "authorization": "Bearer " + api_key}
    return HttpTextEmbedder(base_url.rstrip("/") + "/embeddings", model, dimensions,
                            OpenAIEmbeddingMapping(dimensions if request_dimensions else None), **options)


def ollama_text_embedder(base_url: str, model: str, dimensions: int, *,
                         request_dimensions: bool = False, **options) -> HttpTextEmbedder:
    """base_url is the server root; caller supplies model and expected dimension."""
    if type(request_dimensions) is not bool:
        raise ValueError("embedding dimension request switch must be boolean")
    return HttpTextEmbedder(base_url.rstrip("/") + "/api/embed", model, dimensions,
                            OllamaEmbeddingMapping(dimensions if request_dimensions else None), **options)
