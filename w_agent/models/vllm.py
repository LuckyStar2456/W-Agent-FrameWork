"""vLLM-specific OpenAI-compatible provider differences."""

from __future__ import annotations

from typing import Any, Mapping

from .errors import ModelError, ModelFailure, ModelFailureKind
from .openai_compatible import OpenAICompatibleProvider
from .types import ModelRequest


class VllmProvider(OpenAICompatibleProvider):
    """OpenAI-compatible provider with explicit vLLM request extensions.

    The wire protocol remains Chat Completions. vLLM-only parameters are kept
    under the ``vllm.*`` namespace so applications can use them without
    coupling the provider-neutral request model to one server implementation.
    """

    def _request_body(self, request: ModelRequest, model: str) -> dict[str, Any]:
        body = super()._request_body(request, model)
        structured = request.extensions.get("vllm.structured_outputs")
        if structured is not None:
            if request.response_schema is not None:
                raise self._configuration_error(
                    "conflicting-structured-output",
                    "response_schema and vllm.structured_outputs are mutually exclusive",
                    model,
                )
            if not isinstance(structured, Mapping):
                raise self._configuration_error(
                    "invalid-structured-output",
                    "vllm.structured_outputs must be a mapping",
                    model,
                )
            body["structured_outputs"] = dict(structured)

        typed = {
            "priority": request.extensions.get("vllm.priority"),
            "request_id": request.extensions.get("vllm.request_id"),
            "session_id": request.extensions.get("vllm.session_id"),
        }
        if typed["priority"] is not None and (
            not isinstance(typed["priority"], int)
            or isinstance(typed["priority"], bool)
        ):
            raise self._configuration_error(
                "invalid-priority", "vllm.priority must be an integer", model
            )
        for key in ("request_id", "session_id"):
            value = typed[key]
            if value is not None and (not isinstance(value, str) or not value):
                raise self._configuration_error(
                    f"invalid-{key.replace('_', '-')}",
                    f"vllm.{key} must be a non-empty string",
                    model,
                )
        body.update({key: value for key, value in typed.items() if value is not None})

        overrides = request.extensions.get("vllm.body", {})
        if not isinstance(overrides, Mapping):
            raise self._configuration_error(
                "invalid-body-overrides", "vllm.body must be a mapping", model
            )
        reserved = {
            "max_completion_tokens",
            "max_tokens",
            "messages",
            "model",
            "n",
            "priority",
            "reasoning_effort",
            "request_id",
            "response_format",
            "session_id",
            "stop",
            "stream",
            "stream_options",
            "structured_outputs",
            "temperature",
            "tools",
        } & set(overrides)
        if reserved:
            names = ", ".join(sorted(reserved))
            raise self._configuration_error(
                "reserved-body-overrides",
                f"cannot override reserved request fields: {names}",
                model,
            )
        body.update(overrides)
        return body

    def _configuration_error(self, code: str, message: str, model: str) -> ModelError:
        return ModelError(
            ModelFailure(
                ModelFailureKind.CONFIGURATION,
                code,
                message,
                provider=self.name,
                model=model,
            )
        )
