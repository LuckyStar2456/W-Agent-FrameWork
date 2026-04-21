"""Skill 类定义"""

from pathlib import Path
from typing import Dict, Any, List, Optional

class Skill:
    """技能类"""
    def __init__(self, name: str, description: str, scripts: Dict[str, Path], 
                 tags: List[str] = None, instructions: str = ""):
        self.name = name
        self.description = description
        self.scripts = scripts
        self.tags = tags or []
        self.instructions = instructions
        self._skill_dir = None
    
    def get_script(self, script_name: str) -> Path:
        """获取脚本路径"""
        return self.scripts.get(script_name)
    
    def set_skill_dir(self, skill_dir: Path):
        """设置技能目录"""
        self._skill_dir = skill_dir
    
    def get_skill_dir(self) -> Optional[Path]:
        """获取技能目录"""
        return self._skill_dir

class SkillLoader:
    """技能加载器"""
    @staticmethod
    def load_level1(skill_dir: Path) -> Dict[str, Any]:
        """加载Level 1：仅元数据"""
        # 读取SKILL.md文件获取元数据
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            raise ValueError(f"SKILL.md not found in {skill_dir}")
        
        # 解析SKILL.md
        name = skill_dir.name
        description = ""
        tags = []
        
        with open(skill_md, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            for i, line in enumerate(lines):
                line = line.strip()
                if line.startswith("# "):
                    name = line[2:].strip()
                elif line.startswith("Description:"):
                    if i + 1 < len(lines):
                        description = lines[i + 1].strip()
                elif line.startswith("Tags:"):
                    if i + 1 < len(lines):
                        tags = [tag.strip() for tag in lines[i + 1].split(",")]
        
        return {
            "name": name,
            "description": description,
            "tags": tags,
            "directory": skill_dir
        }
    
    @staticmethod
    def load_level2(skill_dir: Path) -> Dict[str, Any]:
        """加载Level 2：包括指令"""
        level1_data = SkillLoader.load_level1(skill_dir)
        
        # 读取完整指令
        skill_md = skill_dir / "SKILL.md"
        with open(skill_md, 'r', encoding='utf-8') as f:
            instructions = f.read()
        
        level1_data["instructions"] = instructions
        return level1_data
    
    @staticmethod
    def load_level3(skill_dir: Path) -> Skill:
        """加载Level 3：完整技能"""
        level2_data = SkillLoader.load_level2(skill_dir)
        
        # 加载脚本
        scripts = {}
        for script_file in skill_dir.glob("*.py"):
            if script_file.name != "__init__.py":
                scripts[script_file.stem] = script_file
        
        skill = Skill(
            name=level2_data["name"],
            description=level2_data["description"],
            scripts=scripts,
            tags=level2_data.get("tags", []),
            instructions=level2_data.get("instructions", "")
        )
        skill.set_skill_dir(skill_dir)
        return skill

    @staticmethod
    def load_from_directory(skill_dir: Path) -> Skill:
        """从目录加载技能"""
        return SkillLoader.load_level3(skill_dir)

    @staticmethod
    def load_from_dict(data: Dict[str, Any]) -> Skill:
        """从字典加载技能"""
        name = data.get("name", "unknown")
        description = data.get("description", "")
        scripts = {}
        tags = data.get("tags", [])
        instructions = data.get("instructions", "")
        
        for script_name, script_path in data.get("scripts", {}).items():
            scripts[script_name] = Path(script_path)
        
        return Skill(name=name, description=description, scripts=scripts, 
                     tags=tags, instructions=instructions)

class SkillRegistry:
    """技能注册表"""
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SkillRegistry, cls).__new__(cls)
            cls._instance._skills = {}
            cls._instance._skill_index = {}
        return cls._instance
    
    def scan_skills(self, skills_path: Path):
        """扫描技能目录"""
        if not skills_path.exists() or not skills_path.is_dir():
            return
        
        for skill_dir in skills_path.iterdir():
            if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
                try:
                    # 加载Level 1数据
                    skill_data = SkillLoader.load_level1(skill_dir)
                    skill_name = skill_data["name"]
                    self._skills[skill_name] = skill_data
                    
                    # 构建索引
                    for tag in skill_data.get("tags", []):
                        if tag not in self._skill_index:
                            self._skill_index[tag] = []
                        self._skill_index[tag].append(skill_name)
                except Exception as e:
                    print(f"Error scanning skill {skill_dir}: {e}")
    
    def list_skills(self, tags: List[str] = None) -> List[Dict[str, Any]]:
        """列出技能"""
        if not tags:
            return list(self._skills.values())
        
        # 根据标签过滤
        result = []
        for tag in tags:
            if tag in self._skill_index:
                for skill_name in self._skill_index[tag]:
                    if self._skills[skill_name] not in result:
                        result.append(self._skills[skill_name])
        return result
    
    def get_skill(self, name: str, level: int = 3) -> Optional[Any]:
        """获取技能"""
        if name not in self._skills:
            return None
        
        skill_data = self._skills[name]
        skill_dir = skill_data.get("directory")
        
        if level == 1:
            return skill_data
        elif level == 2:
            return SkillLoader.load_level2(skill_dir)
        elif level == 3:
            return SkillLoader.load_level3(skill_dir)
        return None
    
    def search(self, query: str) -> List[Dict[str, Any]]:
        """搜索技能"""
        result = []
        for skill_data in self._skills.values():
            if query.lower() in skill_data["name"].lower() or \
               query.lower() in skill_data["description"].lower():
                result.append(skill_data)
        return result
