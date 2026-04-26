#!/usr/bin/env python3
"""
技能服务
"""
from w_agent import PostConstruct, PreDestroy, WasmSkillSandbox, Skill
from pathlib import Path
import importlib.util
import sys


class SkillService:
    """技能服务"""
    
    def __init__(self, config_manager):
        """初始化"""
        self.config_manager = config_manager
        self.skills_path = None
        self.load_level = None
        
        # 绑定配置
        self.config_manager.bind("skills.path", self, "skills_path")
        self.config_manager.bind("skills.load_level", self, "load_level")
        
        self.sandbox = WasmSkillSandbox()
        self.skills = {}
    
    @PostConstruct(order=1)
    def init(self):
        """初始化后执行"""
        self._load_skills()
        print(f"SkillService initialized with {len(self.skills)} skills")
    
    @PreDestroy(order=1)
    def destroy(self):
        """销毁前执行"""
        print("SkillService destroyed")
    
    def _load_skills(self):
        """加载技能"""
        skills_dir = Path(self.skills_path)
        if not skills_dir.exists():
            print(f"Skills directory not found: {self.skills_path}")
            return
        
        for skill_file in skills_dir.glob("*.py"):
            if skill_file.name == "__init__.py":
                continue
            
            try:
                skill_name = skill_file.stem
                self.skills[skill_name] = Skill(
                    f"{skill_name}_skill",
                    f"{skill_name.capitalize()} Skill",
                    {skill_name: skill_file}
                )
                print(f"Loaded skill: {skill_name}")
            except Exception as e:
                print(f"Failed to load skill {skill_file.name}: {e}")
    
    async def execute_skill(self, skill_name, params):
        """执行技能"""
        if skill_name not in self.skills:
            return f"错误：技能 {skill_name} 不存在"
        
        try:
            skill = self.skills[skill_name]
            result = await self.sandbox.execute(skill, skill_name, params)
            return result
        except Exception as e:
            return f"技能执行失败: {str(e)}"
    
    def get_available_skills(self):
        """获取可用技能列表"""
        return list(self.skills.keys())
