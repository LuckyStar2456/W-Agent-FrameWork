#!/usr/bin/env python3
"""
示例聊天Agent
"""
from w_agent import BaseAgent, PostConstruct, PreDestroy, DynamicConfigManager
import json


class ChatAgent(BaseAgent):
    """示例聊天Agent"""

    
    def __init__(self, llm_service, skill_service, rag_service, config_manager):
        """初始化"""
        self.llm_service = llm_service
        self.skill_service = skill_service
        self.rag_service = rag_service
        self.config_manager = config_manager
        
        self.name = None
        self.version = None
        self.description = None
        self.max_history = None
        
        # 绑定配置
        self.config_manager.bind("system.name", self, "name")
        self.config_manager.bind("system.version", self, "version")
        self.config_manager.bind("system.description", self, "description")
        self.config_manager.bind("system.max_history", self, "max_history")
        
        self.conversation_history = []
    
    @PostConstruct(order=1)
    def init(self):
        """初始化后执行"""
        print(f"ChatAgent initialized: {self.name} v{self.version}")
    
    @PreDestroy(order=1)
    def destroy(self):
        """销毁前执行"""
        print("ChatAgent destroyed")
    
    async def arun(self, prompt: str) -> str:
        """执行Agent"""
        # 添加用户输入到对话历史
        self._add_to_history("user", prompt)
        
        # 分析用户意图
        intent = self._analyze_intent(prompt)
        
        # 根据意图处理
        if intent == "skill":
            result = await self._handle_skill_request(prompt)
        else:
            result = await self._handle_chat_request(prompt)
        
        # 添加Agent回复到对话历史
        self._add_to_history("assistant", result)
        
        return result
    
    def _analyze_intent(self, prompt):
        """分析用户意图"""
        # 简单的意图分析逻辑
        skill_keywords = ["系统", "信息", "时间", "日期", "操作系统", "python"]
        for keyword in skill_keywords:
            if keyword in prompt:
                return "skill"
        return "chat"
    
    async def _handle_skill_request(self, prompt):
        """处理技能请求"""
        # 提取技能名称和参数
        skill_name, params = self._extract_skill_info(prompt)
        
        # 执行技能
        result = await self.skill_service.execute_skill(skill_name, params)
        
        # 处理技能执行结果
        if isinstance(result, dict):
            result = result.get("result", str(result))
        
        return result
    
    async def _handle_chat_request(self, prompt):
        """处理聊天请求"""
        # 构建系统提示
        system_prompt = f"你是{self.name} v{self.version}，{self.description}。请以友好、专业的方式回答用户问题。"
        
        # 构建上下文
        context = self._build_context()
        
        # 使用RAG增强回复
        try:
            # 检索相关文档
            rag_context = await self.rag_service.retrieve_documents(prompt)
            # 使用RAG生成回复
            result = await self.rag_service.generate_with_rag(prompt, rag_context)
        except Exception as e:
            print(f"RAG failed: {e}")
            # 回退到普通LLM生成
            full_prompt = f"{context}\n用户: {prompt}"
            result = await self.llm_service.generate(full_prompt, system_prompt)
        
        return result
    
    def _extract_skill_info(self, prompt):
        """提取技能信息"""
        # 简单的技能信息提取逻辑
        if "时间" in prompt:
            return "system_info", {"type": "time"}
        elif "日期" in prompt:
            return "system_info", {"type": "date"}
        elif "操作系统" in prompt:
            return "system_info", {"type": "os"}
        elif "python" in prompt:
            return "system_info", {"type": "python"}
        else:
            return "system_info", {"type": "all"}
    
    def _build_context(self):
        """构建上下文"""
        context = []
        for msg in self.conversation_history[-min(len(self.conversation_history), 10):]:
            if msg["role"] == "user":
                context.append(f"用户: {msg['content']}")
            else:
                context.append(f"助手: {msg['content']}")
        return "\n".join(context)
    
    def _add_to_history(self, role, content):
        """添加到对话历史"""
        self.conversation_history.append({"role": role, "content": content})
        # 限制历史记录长度
        if len(self.conversation_history) > self.max_history:
            self.conversation_history = self.conversation_history[-self.max_history:]
    
    def clear_history(self):
        """清空对话历史"""
        self.conversation_history = []
    
    def get_available_skills(self):
        """获取可用技能列表"""
        return self.skill_service.get_available_skills()
