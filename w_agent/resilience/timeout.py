import asyncio

class LLMTimeoutError(Exception):
    """LLM调用超时异常"""
    pass

async def call_with_timeout(coro, timeout: float, partial_timeout: float = None):
    """支持流式响应的分段超时"""
    try:
        if partial_timeout:
            # 流式场景：每个 chunk 单独超时
            async for chunk in coro:
                yield await asyncio.wait_for(chunk, timeout=partial_timeout)
        else:
            return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        raise LLMTimeoutError(f"LLM call exceeded timeout {timeout}s")