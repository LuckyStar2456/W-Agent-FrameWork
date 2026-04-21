#!/usr/bin/env python3
"""
示例聊天Agent应用
"""
import asyncio
import sys
import json
from pathlib import Path

# 添加当前目录到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from w_agent.core.doctor import Doctor
from w_agent.container.bean_factory import BeanFactory
from w_agent.config.dynamic_config import DynamicConfigManager
from w_agent.lifecycle.manager import LifecycleManager

from src.services.llm_service import LLMService
from src.services.skill_service import SkillService
from src.services.redis_service import RedisService
from src.services.mysql_service import MySQLService
from src.services.rag_service import RAGService
from src.agents.chat_agent import ChatAgent


async def load_config(config_manager, config_path):
    """加载配置文件"""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
            
        # 递归设置配置
        def set_config_recursive(prefix, data):
            if isinstance(data, dict):
                for key, value in data.items():
                    new_prefix = f"{prefix}.{key}" if prefix else key
                    set_config_recursive(new_prefix, value)
            else:
                config_manager.set(prefix, data)
        
        set_config_recursive("", config_data)
        return True
    except Exception as e:
        print(f"加载配置文件失败: {e}")
        return False


def check_api_keys(config_manager):
    """检查API密钥"""
    llm_api_key = config_manager.get("llm.api_key")
    if not llm_api_key:
        print("警告：LLM API密钥未配置，请在config.json中填写")
        print("当前将使用模拟响应")
        return False
    return True


async def main():
    """主函数"""
    # 运行系统检查
    print("=== 运行系统检查... ===")
    doctor = Doctor()
    results = doctor.run_all_checks()
    all_passed = doctor.print_results(results)
    
    # 检查核心组件
    core_components = ["bean_factory", "config_manager", "lifecycle_manager", "event_bus", "resilience_manager"]
    core_failed = any(not results[component][0] for component in core_components)
    
    if core_failed:
        print("\n核心组件检查失败，退出...")
        return
    else:
        print("\n核心组件检查通过，启动应用...")
    
    # 初始化配置管理器
    config_manager = DynamicConfigManager()
    config_path = Path(__file__).parent / "config" / "config.json"
    
    # 加载配置文件
    if not await load_config(config_manager, config_path):
        print("配置加载失败，退出...")
        return
    
    # 检查API密钥
    api_available = check_api_keys(config_manager)
    
    # 初始化Bean工厂
    bean_factory = BeanFactory()
    
    # 注册服务
    llm_service = LLMService(config_manager)
    bean_factory.register_bean("llm_service", llm_service)
    
    skill_service = SkillService(config_manager)
    bean_factory.register_bean("skill_service", skill_service)
    
    redis_service = RedisService(config_manager)
    bean_factory.register_bean("redis_service", redis_service)
    
    mysql_service = MySQLService(config_manager)
    bean_factory.register_bean("mysql_service", mysql_service)
    
    rag_service = RAGService(config_manager, llm_service, redis_service)
    bean_factory.register_bean("rag_service", rag_service)
    
    # 注册Agent
    chat_agent = ChatAgent(llm_service, skill_service, rag_service, config_manager)
    bean_factory.register_bean("chat_agent", chat_agent)
    
    # 初始化生命周期管理器
    lifecycle_manager = LifecycleManager()
    lifecycle_manager.register(llm_service)
    lifecycle_manager.register(skill_service)
    lifecycle_manager.register(redis_service)
    lifecycle_manager.register(mysql_service)
    lifecycle_manager.register(rag_service)
    lifecycle_manager.register(chat_agent)
    
    # 启动生命周期
    await lifecycle_manager.post_construct_all()
    
    try:
        print("\n=== 聊天Agent就绪 ===")
        print("输入 'exit' 退出")
        print("输入 'clear' 清空对话历史")
        print("输入 'skills' 查看可用技能")
        print("\n你: ", end="")
        
        while True:
            # 获取用户输入
            try:
                prompt = input().strip()
            except EOFError:
                break
            
            if prompt.lower() == "exit":
                break
            elif prompt.lower() == "clear":
                chat_agent.clear_history()
                print("对话历史已清空")
                print("\n你: ", end="")
                continue
            elif prompt.lower() == "skills":
                skills = chat_agent.get_available_skills()
                print(f"可用技能: {', '.join(skills)}")
                print("\n你: ", end="")
                continue
            
            # 执行Agent
            agent = await bean_factory.get_bean("chat_agent")
            result = await agent.arun(prompt)
            
            # 输出结果
            print(f"Agent: {result}")
            print("\n你: ", end="")
            
    finally:
        # 停止生命周期
        await lifecycle_manager.pre_destroy_all()
        print("\n=== 应用已停止 ===")


if __name__ == "__main__":
    asyncio.run(main())
