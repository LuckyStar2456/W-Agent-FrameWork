import importlib
from types import SimpleNamespace

import pytest


async def test_fastapi_default_agent_chain():
    from w_agent.deployment.fastapi_depends import get_agent

    agent = await get_agent()
    assert await agent.arun("hello") == "W-Agent: hello"


async def test_serverless_default_agent_chain(tmp_path, monkeypatch):
    monkeypatch.setenv("W_AGENT_SNAPSHOT_PATH", str(tmp_path / "factory.snapshot"))
    import serverless.lambda_handler as handler

    handler.bean_factory = None
    response = await handler.handle_request(
        {"prompt": "hello"}, SimpleNamespace(aws_request_id="test-request")
    )
    assert response == {"statusCode": 200, "body": {"response": "W-Agent: hello"}}

    # A cold start restored from the snapshot must expose the same agent.
    handler.bean_factory = None
    await handler.initialize_bean_factory()
    agent = await handler.bean_factory.get_bean("default_agent")
    assert await agent.arun("again") == "W-Agent: again"


def test_runtime_version_matches_distribution_metadata():
    import w_agent
    from importlib.metadata import version

    assert w_agent.__version__ == version("wagent-framework")
