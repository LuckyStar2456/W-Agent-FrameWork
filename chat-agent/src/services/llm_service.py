#!/usr/bin/env python3
"""
示例LLM服务
"""
from w_agent.core.decorators import PostConstruct, PreDestroy
from w_agent.config.dynamic_config import DynamicConfigManager
from w_agent.resilience.bulkhead import ResilienceManager
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
        self.config_manager.bind("llm.api_key", self, "api_key")
        self.config_manager.bind("llm.model", self, "model")
        self.config_manager.bind("llm.temperature", self, "temperature")
        self.config_manager.bind("llm.max_tokens", self, "max_tokens")
        self.config_manager.bind("llm.timeout", self, "timeout")
        
        self.resilience_manager = ResilienceManager()
        self.client = None
    
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
    
    async def generate(self, prompt, system_prompt=None):
        """生成文本"""
        if not self.client:
            return "错误：LLM服务未初始化，请配置API密钥"
        
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            response = await asyncio.to_thread(
                self.client.chat.completions.create,
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens
            )
            
            return response.choices[0].message.content
        except Exception as e:
            return f"LLM生成失败: {str(e)}"
