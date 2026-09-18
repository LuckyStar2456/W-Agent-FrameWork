"""Composable provider templates and a small replaceable template registry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from .http_provider import (
    HttpModelProfile,
    HttpModelProvider,
    HttpProviderTransport,
)
from .native_mappings import (
    AnthropicMessagesMapping,
    GeminiGenerateContentMapping,
    OllamaChatMapping,
    QwenDashScopeMapping,
)
from .openai_responses import OpenAIResponsesMapping
from .openai_compatible import (
    OpenAICompatibleModelProfile,
    OpenAICompatibleProvider,
    OpenAICompatibleTransport,
)
from .provider import ModelProvider
from .types import ModelCapability
from .vllm import VllmProvider


_TEXT = frozenset(
    {
        ModelCapability.TEXT_INPUT,
        ModelCapability.TEXT_OUTPUT,
        ModelCapability.STREAMING,
    }
)
_TEXT_TOOLS_JSON = _TEXT | {
    ModelCapability.TOOL_CALLING,
    ModelCapability.STRUCTURED_OUTPUT,
}
_OPENAI_RESPONSES = _TEXT_TOOLS_JSON | {
    ModelCapability.IMAGE_INPUT,
    ModelCapability.REASONING,
    ModelCapability.PROMPT_CACHE,
}


@dataclass(frozen=True, slots=True)
class ProviderTemplate:
    """Named provider builder that can be copied or replaced by applications."""

    key: str
    display_name: str
    protocol: str
    default_base_url: str | None
    builder: Callable[..., ModelProvider]

    def build(self, **options: Any) -> ModelProvider:
        """Build an independent provider instance."""

        return self.builder(**options)


class ProviderTemplateRegistry:
    """Mutable local registry; it owns no global process state."""

    def __init__(self, templates: tuple[ProviderTemplate, ...] = ()) -> None:
        self._templates: dict[str, ProviderTemplate] = {}
        for template in templates:
            self.register(template)

    def register(
        self, template: ProviderTemplate, *, replace: bool = False
    ) -> ProviderTemplate | None:
        previous = self._templates.get(template.key)
        if previous is not None and not replace:
            raise ValueError(f"provider template {template.key!r} is already registered")
        self._templates[template.key] = template
        return previous

    def unregister(self, key: str) -> ProviderTemplate:
        try:
            return self._templates.pop(key)
        except KeyError as exc:
            raise KeyError(f"unknown provider template {key!r}") from exc

    def get(self, key: str) -> ProviderTemplate:
        try:
            return self._templates[key]
        except KeyError as exc:
            raise KeyError(f"unknown provider template {key!r}") from exc

    def build(self, key: str, **options: Any) -> ModelProvider:
        return self.get(key).build(**options)

    def templates(self) -> tuple[ProviderTemplate, ...]:
        return tuple(self._templates[key] for key in sorted(self._templates))


def anthropic_provider(
    *,
    api_key: str | None = None,
    name: str = "anthropic",
    base_url: str = "https://api.anthropic.com",
    api_version: str = "2023-06-01",
    default_model: str | None = None,
    profiles: tuple[HttpModelProfile, ...] = (),
    timeout: float = 60.0,
    headers: Mapping[str, str] | None = None,
    transport: HttpProviderTransport | None = None,
) -> HttpModelProvider:
    request_headers = {
        "anthropic-version": api_version,
        **({"x-api-key": api_key} if api_key else {}),
        **dict(headers or {}),
    }
    return HttpModelProvider(
        name=name,
        base_url=base_url,
        mapping=AnthropicMessagesMapping(),
        default_model=default_model,
        profiles=profiles,
        default_capabilities=_TEXT_TOOLS_JSON | {ModelCapability.IMAGE_INPUT},
        timeout=timeout,
        headers=request_headers,
        transport=transport,
    )


def gemini_provider(
    *,
    api_key: str | None = None,
    name: str = "gemini",
    base_url: str = "https://generativelanguage.googleapis.com",
    default_model: str | None = None,
    profiles: tuple[HttpModelProfile, ...] = (),
    timeout: float = 60.0,
    headers: Mapping[str, str] | None = None,
    transport: HttpProviderTransport | None = None,
) -> HttpModelProvider:
    request_headers = {
        **({"x-goog-api-key": api_key} if api_key else {}),
        **dict(headers or {}),
    }
    return HttpModelProvider(
        name=name,
        base_url=base_url,
        mapping=GeminiGenerateContentMapping(),
        default_model=default_model,
        profiles=profiles,
        default_capabilities=_TEXT_TOOLS_JSON
        | {ModelCapability.IMAGE_INPUT, ModelCapability.AUDIO_INPUT},
        timeout=timeout,
        headers=request_headers,
        transport=transport,
    )


def ollama_provider(
    *,
    api_key: str | None = None,
    name: str = "ollama",
    base_url: str = "http://127.0.0.1:11434",
    default_model: str | None = None,
    profiles: tuple[HttpModelProfile, ...] = (),
    timeout: float = 60.0,
    headers: Mapping[str, str] | None = None,
    transport: HttpProviderTransport | None = None,
) -> HttpModelProvider:
    request_headers = {
        **({"Authorization": f"Bearer {api_key}"} if api_key else {}),
        **dict(headers or {}),
    }
    return HttpModelProvider(
        name=name,
        base_url=base_url,
        mapping=OllamaChatMapping(),
        default_model=default_model,
        profiles=profiles,
        default_capabilities=_TEXT_TOOLS_JSON | {ModelCapability.IMAGE_INPUT},
        timeout=timeout,
        headers=request_headers,
        transport=transport,
    )


def qwen_native_provider(
    *,
    api_key: str | None = None,
    name: str = "qwen-native",
    base_url: str = "https://dashscope-intl.aliyuncs.com",
    default_model: str | None = None,
    profiles: tuple[HttpModelProfile, ...] = (),
    timeout: float = 60.0,
    headers: Mapping[str, str] | None = None,
    transport: HttpProviderTransport | None = None,
) -> HttpModelProvider:
    request_headers = {
        **({"Authorization": f"Bearer {api_key}"} if api_key else {}),
        **dict(headers or {}),
    }
    return HttpModelProvider(
        name=name,
        base_url=base_url,
        mapping=QwenDashScopeMapping(),
        default_model=default_model,
        profiles=profiles,
        default_capabilities=_TEXT_TOOLS_JSON,
        timeout=timeout,
        headers=request_headers,
        transport=transport,
    )


def openai_responses_provider(
    *,
    api_key: str | None = None,
    name: str = "openai-responses",
    base_url: str = "https://api.openai.com/v1",
    default_model: str | None = None,
    profiles: tuple[HttpModelProfile, ...] = (),
    timeout: float = 60.0,
    headers: Mapping[str, str] | None = None,
    transport: HttpProviderTransport | None = None,
) -> HttpModelProvider:
    """Build an OpenAI Responses API provider on the generic HTTP runtime."""

    request_headers = {
        **({"Authorization": f"Bearer {api_key}"} if api_key else {}),
        **dict(headers or {}),
    }
    return HttpModelProvider(
        name=name,
        base_url=base_url,
        mapping=OpenAIResponsesMapping(),
        default_model=default_model,
        profiles=profiles,
        default_capabilities=_OPENAI_RESPONSES,
        timeout=timeout,
        headers=request_headers,
        transport=transport,
    )


def deepseek_provider(
    *,
    api_key: str | None = None,
    name: str = "deepseek",
    base_url: str = "https://api.deepseek.com",
    default_model: str | None = None,
    profiles: tuple[OpenAICompatibleModelProfile, ...] = (),
    discover_models: bool = True,
    timeout: float = 60.0,
    headers: Mapping[str, str] | None = None,
    transport: OpenAICompatibleTransport | None = None,
) -> OpenAICompatibleProvider:
    return _compatible_provider(
        name=name,
        base_url=base_url,
        api_key=api_key,
        default_model=default_model,
        profiles=profiles,
        discover_models=discover_models,
        timeout=timeout,
        headers=headers,
        transport=transport,
        default_capabilities=_TEXT_TOOLS_JSON,
        max_tokens_field="max_tokens",
    )


def glm_provider(
    *,
    api_key: str | None = None,
    name: str = "glm",
    base_url: str = "https://open.bigmodel.cn/api/paas/v4",
    default_model: str | None = None,
    profiles: tuple[OpenAICompatibleModelProfile, ...] = (),
    discover_models: bool = True,
    timeout: float = 60.0,
    headers: Mapping[str, str] | None = None,
    transport: OpenAICompatibleTransport | None = None,
) -> OpenAICompatibleProvider:
    return _compatible_provider(
        name=name,
        base_url=base_url,
        api_key=api_key,
        default_model=default_model,
        profiles=profiles,
        discover_models=discover_models,
        timeout=timeout,
        headers=headers,
        transport=transport,
        default_capabilities=_TEXT_TOOLS_JSON,
        max_tokens_field="max_tokens",
    )


def qwen_compatible_provider(
    *,
    api_key: str | None = None,
    name: str = "qwen",
    base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    default_model: str | None = None,
    profiles: tuple[OpenAICompatibleModelProfile, ...] = (),
    discover_models: bool = True,
    timeout: float = 60.0,
    headers: Mapping[str, str] | None = None,
    transport: OpenAICompatibleTransport | None = None,
) -> OpenAICompatibleProvider:
    return _compatible_provider(
        name=name,
        base_url=base_url,
        api_key=api_key,
        default_model=default_model,
        profiles=profiles,
        discover_models=discover_models,
        timeout=timeout,
        headers=headers,
        transport=transport,
        default_capabilities=_TEXT_TOOLS_JSON,
    )


def turbo_provider(
    *,
    base_url: str,
    api_key: str | None = None,
    name: str = "turbo",
    default_model: str | None = None,
    profiles: tuple[OpenAICompatibleModelProfile, ...] = (),
    discover_models: bool = False,
    timeout: float = 60.0,
    headers: Mapping[str, str] | None = None,
    transport: OpenAICompatibleTransport | None = None,
) -> OpenAICompatibleProvider:
    """Build a Turbo AI/SIAM.AI template with a deployment-specific base URL."""

    if not discover_models and not profiles:
        if default_model is None:
            raise ValueError(
                "Turbo needs default_model or profiles when discovery is disabled"
            )
        profiles = (OpenAICompatibleModelProfile(default_model),)
    return _compatible_provider(
        name=name,
        base_url=base_url,
        api_key=api_key,
        default_model=default_model,
        profiles=profiles,
        discover_models=discover_models,
        timeout=timeout,
        headers=headers,
        transport=transport,
        default_capabilities=_TEXT,
        max_tokens_field="max_tokens",
        include_stream_usage=False,
    )


def vllm_provider(
    *,
    api_key: str | None = None,
    name: str = "vllm",
    base_url: str = "http://127.0.0.1:8000/v1",
    default_model: str | None = None,
    profiles: tuple[OpenAICompatibleModelProfile, ...] = (),
    discover_models: bool = True,
    timeout: float = 60.0,
    headers: Mapping[str, str] | None = None,
    transport: OpenAICompatibleTransport | None = None,
) -> VllmProvider:
    """Build a vLLM Chat Completions provider with namespaced extensions."""

    if not discover_models and not profiles and default_model is not None:
        profiles = (
            OpenAICompatibleModelProfile(default_model, _TEXT_TOOLS_JSON),
        )
    return VllmProvider(
        name=name,
        base_url=base_url,
        api_key=api_key,
        default_model=default_model,
        profiles=profiles,
        default_capabilities=_TEXT_TOOLS_JSON,
        discover_models=discover_models,
        timeout=timeout,
        headers=headers,
        max_tokens_field="max_tokens",
        include_stream_usage=True,
        transport=transport,
    )


def _compatible_provider(
    *,
    name: str,
    base_url: str,
    api_key: str | None,
    default_model: str | None,
    profiles: tuple[OpenAICompatibleModelProfile, ...],
    discover_models: bool,
    timeout: float,
    headers: Mapping[str, str] | None,
    transport: OpenAICompatibleTransport | None,
    default_capabilities: frozenset[ModelCapability],
    max_tokens_field: str = "max_completion_tokens",
    include_stream_usage: bool = True,
) -> OpenAICompatibleProvider:
    if not discover_models and not profiles and default_model is not None:
        profiles = (
            OpenAICompatibleModelProfile(
                default_model,
                default_capabilities,
            ),
        )
    return OpenAICompatibleProvider(
        name=name,
        base_url=base_url,
        api_key=api_key,
        default_model=default_model,
        profiles=profiles,
        default_capabilities=default_capabilities,
        discover_models=discover_models,
        timeout=timeout,
        headers=headers,
        max_tokens_field=max_tokens_field,
        include_stream_usage=include_stream_usage,
        transport=transport,
    )


BUILTIN_PROVIDER_TEMPLATES: Mapping[str, ProviderTemplate] = MappingProxyType(
    {
        template.key: template
        for template in (
            ProviderTemplate(
                "openai-responses",
                "OpenAI Responses",
                "openai-responses",
                "https://api.openai.com/v1",
                openai_responses_provider,
            ),
            ProviderTemplate(
                "anthropic",
                "Anthropic",
                "anthropic-messages",
                "https://api.anthropic.com",
                anthropic_provider,
            ),
            ProviderTemplate(
                "gemini",
                "Google Gemini",
                "gemini-generate-content",
                "https://generativelanguage.googleapis.com",
                gemini_provider,
            ),
            ProviderTemplate(
                "ollama",
                "Ollama",
                "ollama-chat",
                "http://127.0.0.1:11434",
                ollama_provider,
            ),
            ProviderTemplate(
                "qwen-native",
                "Qwen DashScope Native",
                "dashscope-generation",
                "https://dashscope-intl.aliyuncs.com",
                qwen_native_provider,
            ),
            ProviderTemplate(
                "deepseek",
                "DeepSeek",
                "openai-compatible",
                "https://api.deepseek.com",
                deepseek_provider,
            ),
            ProviderTemplate(
                "glm",
                "GLM / BigModel",
                "openai-compatible",
                "https://open.bigmodel.cn/api/paas/v4",
                glm_provider,
            ),
            ProviderTemplate(
                "qwen",
                "Qwen OpenAI Compatible",
                "openai-compatible",
                "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
                qwen_compatible_provider,
            ),
            ProviderTemplate(
                "vllm",
                "vLLM",
                "openai-compatible-vllm",
                "http://127.0.0.1:8000/v1",
                vllm_provider,
            ),
            ProviderTemplate(
                "turbo",
                "Turbo AI / SIAM.AI",
                "openai-compatible",
                None,
                turbo_provider,
            ),
        )
    }
)


def builtin_provider_template_registry() -> ProviderTemplateRegistry:
    """Return a mutable registry initialized from immutable built-ins."""

    return ProviderTemplateRegistry(tuple(BUILTIN_PROVIDER_TEMPLATES.values()))
