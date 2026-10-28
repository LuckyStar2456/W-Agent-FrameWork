"""Draft named knowledge/runtime composition regressions; unexecuted."""

import pytest

from w_agent import (
    BlockEnd, BlockStart, FinishEvent, FinishReason, KnowledgeDocument,
    LocalKnowledgeBinding, LocalKnowledgeConfig, LocalRuntimeConfigError,
    MessageRole, ModelCapability, ModelDescriptor, ModelMessage, ProviderTemplate,
    ProviderTemplateRegistry, TextContent, TokenUsage, UsageEvent,
    assemble_local_runtime, local_runtime_config_from_mapping,
)


class Retriever:
    def __init__(self):
        self.queries = []
        self.closed = False

    async def retrieve(self, query, *, limit):
        self.queries.append((query, limit))
        return (KnowledgeDocument("doc", "REFERENCE_BODY", "local:manual.md", "Manual"),)

    async def aclose(self):
        self.closed = True


class Provider:
    def __init__(self, name, model):
        self.name, self.model, self.requests = name, model, []

    async def list_models(self):
        return (await self.resolve(self.model),)

    async def resolve(self, model):
        return ModelDescriptor(self.name, self.model, frozenset({ModelCapability.TEXT_INPUT, ModelCapability.TEXT_OUTPUT}))

    async def stream(self, request, *, cancellation=None):
        self.requests.append(request)
        yield BlockStart(0, "text")
        yield BlockEnd(0, TextContent("answer"))
        yield UsageEvent(TokenUsage(3, 1))
        yield FinishEvent(FinishReason.STOP)


def configuration():
    return {"provider": {"template": "fake", "model": "m", "name": "p"},
            "agent": {"max_steps": 1, "max_tool_calls": 0}, "knowledge": {"binding": "manual"}}


def runtime(tmp_path, retriever=None):
    providers = []

    def build(**options):
        provider = Provider(options["name"], options["default_model"])
        providers.append(provider)
        return provider

    templates = ProviderTemplateRegistry((ProviderTemplate("fake", "Fake", "p", None, build),))
    kwargs = {} if retriever is None else {"knowledge_bindings": {"manual": LocalKnowledgeBinding(retriever, limit=2)}}
    instance = assemble_local_runtime(local_runtime_config_from_mapping(configuration()), tmp_path,
                                      templates=templates, **kwargs)
    return instance, providers[0]


@pytest.mark.asyncio
async def test_assembly_and_run_without_query_never_retrieve(tmp_path):
    retriever = Retriever()
    instance, provider = runtime(tmp_path, retriever)
    assert not retriever.queries
    async with instance:
        await instance.run("plain run")
    assert not retriever.queries and len(provider.requests) == 1
    assert not retriever.closed  # Borrowed dependency belongs to its host.


@pytest.mark.asyncio
async def test_explicit_query_composes_user_data_before_current_input(tmp_path):
    retriever = Retriever()
    instance, provider = runtime(tmp_path, retriever)
    async with instance:
        await instance.run("CURRENT", knowledge_query="EXPLICIT_QUERY", confirm_knowledge_query=True)
    assert retriever.queries == [("EXPLICIT_QUERY", 2)]
    messages = provider.requests[0].messages
    reference = next(message for message in messages if "REFERENCE_BODY" in "".join(block.text for block in message.content))
    assert reference.role == MessageRole.USER
    assert messages[-1].content[0].text == "CURRENT"
    assert "EXPLICIT_QUERY" not in "".join(block.text for message in messages for block in message.content)


@pytest.mark.asyncio
@pytest.mark.parametrize("options", [
    {"knowledge_query": "query"}, {"knowledge_query": "query", "confirm_knowledge_query": 1},
    {"knowledge_query": " ", "confirm_knowledge_query": True}, {"confirm_knowledge_query": True},
])
async def test_query_consent_and_bounds_checked_before_session_creation(tmp_path, options):
    retriever = Retriever()
    instance, provider = runtime(tmp_path, retriever)
    with pytest.raises(ValueError):
        await instance.run("question", **options)
    assert not retriever.queries and not provider.requests
    await instance.aclose()


@pytest.mark.asyncio
async def test_missing_catalog_is_allowed_until_explicit_knowledge_use(tmp_path):
    instance, provider = runtime(tmp_path)
    with pytest.raises(ValueError, match="authorized binding"):
        await instance.run("question", knowledge_query="query", confirm_knowledge_query=True)
    assert not provider.requests
    async with instance:
        await instance.run("plain run")
    assert len(provider.requests) == 1


@pytest.mark.asyncio
async def test_knowledge_only_does_not_reuse_history_or_invoke_history_callback(tmp_path):
    retriever = Retriever()
    instance, provider = runtime(tmp_path, retriever)

    class ForbiddenHistory:
        def project(self, session):
            pytest.fail("disabled history callback was invoked")

    async with instance:
        first = await instance.run("OLD_PRIVATE_INPUT", record_inputs=True)
        await instance.run_messages((ModelMessage.text(MessageRole.USER, "CURRENT"),),
                                    session_id=first.session.session_id, include_history=False,
                                    history_policy=ForbiddenHistory(), knowledge_query="query", confirm_knowledge_query=True)
    text = "".join(block.text for message in provider.requests[-1].messages for block in message.content)
    assert "REFERENCE_BODY" in text and "OLD_PRIVATE_INPUT" not in text
    assert all(block.text != "answer" for message in provider.requests[-1].messages for block in message.content)


@pytest.mark.parametrize("selection", [{}, {"binding": "../private"}, {"binding": "manual", "factory": "hidden:code"}])
def test_config_allows_only_an_opaque_selection(selection):
    with pytest.raises(LocalRuntimeConfigError):
        local_runtime_config_from_mapping({**configuration(), "knowledge": selection})
    assert local_runtime_config_from_mapping(configuration()).knowledge == LocalKnowledgeConfig("manual")
