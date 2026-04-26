#!/usr/bin/env python3
"""
示例LLM服务
"""
from w_agent import PostConstruct, PreDestroy, DynamicConfigManager, ResilienceManager
from w_agent.observability.logging import LogEnable
import openai
import asyncio


class LLMService:
    """示例LLM服务"""

    def __init__(self, config_manager):
        """初始化"""
        self.config_manager = config_manager
        self.api_key = None
        self.model = None
        self.temperature = None
        self.max_tokens = None
        self.timeout = None
        
        # 绑定配置
        self._bind_config()
        
        self.resilience_manager = ResilienceManager()
        self.client = None
    
    def _bind_config(self):
        """绑定配置"""
        self.config_manager.bind("llm.api_key", self, "api_key")
        self.config_manager.bind("llm.model", self, "model")
        self.config_manager.bind("llm.temperature", self, "temperature")
        self.config_manager.bind("llm.max_tokens", self, "max_tokens")
        self.config_manager.bind("llm.timeout", self, "timeout")
    
    @PostConstruct(order=1)
    def init(self):
        """初始化后执行"""
        if self.api_key:
            try:
                self.client = openai.OpenAI(api_key=self.api_key, timeout=self.timeout)
                print("LLMService initialized with OpenAI client")
            except Exception as e:
                print(f"Failed to initialize OpenAI client: {e}")
                self.client = None
        else:
            print("LLMService initialized without API key")
    
    @PreDestroy(order=1)
    def destroy(self):
        """销毁前执行"""
        print("LLMService destroyed")
    
    @LogEnable(log_args=True, log_result=True, log_duration=True)
    async def generate(self, prompt, system_prompt=None):
        """生成文本"""
        if not self.client:
            return "错误：LLM服务未初始化，请配置API密钥"
        
        try:
            messages = self._build_messages(prompt, system_prompt)
            response = await self._create_completion(messages)
            return self._extract_response_content(response)
        except Exception as e:
            return f"LLM生成失败: {str(e)}"
    
    def _build_messages(self, prompt, system_prompt=None):
        """构建消息列表"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return messages
    
    async def _create_completion(self, messages):
        """创建完成"""
        return await asyncio.to_thread(
            self.client.chat.completions.create,
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens
        )
    
    def _extract_response_content(self, response):
        """提取响应内容"""
        return response.choices[0].message.content
