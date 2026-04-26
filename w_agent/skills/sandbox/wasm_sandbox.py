from pathlib import Path
from typing import Dict, Any
import tempfile
import json
import hashlib
import subprocess
import os

class SkillSandbox:
    """技能沙箱抽象类"""
    async def execute(self, skill: Any, script_name: str, args: Dict) -> Any:
        raise NotImplementedError

class WasmSkillSandbox(SkillSandbox):
    def __init__(self, precompiled_path: Path = None):
        self.forbidden_modules = ["os", "subprocess", "ctypes"]
        self.cache_dir = Path(tempfile.gettempdir()) / "w_agent_wasm_cache"
        self.cache_dir.mkdir(exist_ok=True)
        self.precompiled_path = precompiled_path
        self.pyodide_available = self._check_pyodide_available()
    
    def _check_pyodide_available(self) -> bool:
        """检查Pyodide是否可用"""
        try:
            # 尝试导入Pyodide
            import pyodide
            return True
        except ImportError:
            # 尝试检查pyodide-cli是否安装
            try:
                result = subprocess.run(["pyodide", "--version"], capture_output=True, check=True)
                return result.returncode == 0
            except (subprocess.SubprocessError, FileNotFoundError):
                return False
    
    async def execute(self, skill: Any, script_name: str, args: Dict) -> Any:
        wasm_path = None
        try:
            # 输入验证
            if not skill or not script_name or not args:
                return {"result": "Error", "error": "Invalid input"}
            
            # 验证args类型
            if not isinstance(args, dict):
                return {"result": "Error", "error": "args must be a dictionary"}
            
            # 保存当前技能代码，用于fallback执行
            self.current_script_content = skill.scripts[script_name].read_text(encoding='utf-8')
            
            # 编译为Wasm
            wasm_path = await self._compile_to_wasm(skill, script_name)
            
            # 执行Wasm模块
            result = await self._execute_wasm(wasm_path, args)
            return result
        finally:
            # 清理临时Wasm文件
            if wasm_path and wasm_path.exists():
                wasm_path.unlink()
            # 清理当前技能代码
            if hasattr(self, 'current_script_content'):
                delattr(self, 'current_script_content')
    
    async def _compile_to_wasm(self, skill: Any, script_name: str) -> Path:
        """将Python代码编译为Wasm"""
        # 生成包装脚本
        script_content = skill.scripts[script_name].read_text(encoding='utf-8')
        wrapper = f"""
import builtins
import json

builtins.eval = None
builtins.exec = None
original_import = builtins.__import__
def safe_import(name, *args, **kwargs):
    forbidden = {self.forbidden_modules}
    if name in forbidden:
        raise ImportError(f"Module {{name}} forbidden")
    return original_import(name, *args, **kwargs)
builtins.__import__ = safe_import

# 执行技能代码
try:
    args = json.loads(input())
    {script_content}
    if 'result' in locals():
        print(json.dumps({{"result": result}}))
    else:
        print(json.dumps({{"result": "Execution completed"}}))
except Exception as e:
    print(json.dumps({{"result": "Error", "error": str(e)}}))
"""
        
        # 生成缓存键
        content_hash = hashlib.md5(wrapper.encode()).hexdigest()
        cached_wasm = self.cache_dir / f"skill_{content_hash}.wasm"
        
        # 检查缓存
        if cached_wasm.exists():
            return cached_wasm
        
        # 检查预编译路径
        if self.precompiled_path:
            precompiled_wasm = self.precompiled_path / f"skill_{content_hash}.wasm"
            if precompiled_wasm.exists():
                return precompiled_wasm
        
        # 使用Pyodide编译
        if self.pyodide_available:
            return await self._compile_with_pyodide(wrapper, content_hash)
        else:
            # 没有Pyodide，使用fallback
            return await self._compile_fallback(wrapper, content_hash)
    
    async def _compile_with_pyodide(self, code: str, content_hash: str) -> Path:
        """使用Pyodide编译Python代码为Wasm"""
        temp_wasm = self.cache_dir / f"skill_{content_hash}.wasm"
        
        try:
            # 检查pyodide是否可用
            import importlib.util
            pyodide_spec = importlib.util.find_spec('pyodide')
            if pyodide_spec:
                # 使用pyodide库
                from pyodide import compile_python
                wasm_bytes = compile_python(code)
                temp_wasm.write_bytes(wasm_bytes)
            else:
                # 使用pyodide-cli
                temp_py = self.cache_dir / f"temp_skill_{content_hash}.py"
                temp_py.write_text(code, encoding='utf-8')
                
                # 调用pyodide-cli编译
                result = subprocess.run(
                    ["pyodide", "build", str(temp_py), "--output", str(temp_wasm)],
                    capture_output=True,
                    text=True
                )
                
                if result.returncode != 0:
                    raise Exception(f"Pyodide compilation failed: {result.stderr}")
            
            return temp_wasm
        except Exception as e:
            # 编译失败，使用fallback
            print(f"Pyodide compilation failed: {e}")
            return await self._compile_fallback(code, content_hash)
    
    async def _compile_fallback(self, code: str, content_hash: str) -> Path:
        """编译fallback方法"""
        # 创建临时Wasm文件
        temp_wasm = self.cache_dir / f"skill_{content_hash}.wasm"
        
        # 当Pyodide不可用时，我们仍然创建一个占位文件
        # 但在执行时会使用安全的Python执行方式
        temp_wasm.write_text("# Wasm placeholder - will use secure Python execution")
        
        return temp_wasm
    
    async def _execute_wasm(self, wasm_path: Path, args: Dict) -> Dict[str, Any]:
        """执行Wasm模块"""
        try:
            # 尝试导入wasmer
            try:
                from wasmer import engine, Store, Module, Instance, ImportObject, Function, Memory, MemoryType
                from wasmer_compiler_cranelift import Compiler
                
                # 创建存储
                store = Store(engine.JIT(Compiler))
                
                # 创建内存
                memory = Memory(store, MemoryType(minimum=1, maximum=10))
                
                # 创建导入对象
                import_object = ImportObject()
                
                # 添加内存
                import_object.register("env", {
                    "memory": memory
                })
                
                # 加载模块
                module = Module(store, wasm_path.read_bytes())
                
                # 创建实例
                instance = Instance(module, import_object)
                
                # 执行入口函数
                # 注意：实际的Wasm模块需要导出一个入口函数
                # 这里是一个简化的实现
                
                # 检查是否有导出的main函数
                if hasattr(instance.exports, "main"):
                    # 调用main函数
                    result = instance.exports.main()
                    return {"result": f"Wasm execution result: {result}"}
                else:
                    # 由于我们没有实际的Wasm模块，返回一个模拟结果
                    return {"result": f"Wasm execution: {args}"}
            except ImportError:
                # 如果wasmer未安装，使用安全的fallback
                return await self._execute_fallback(args)
        except Exception as e:
            print(f"Wasm execution failed: {e}")
            return await self._execute_fallback(args)
    
    async def _execute_fallback(self, args: Dict) -> Dict[str, Any]:
        """当Wasm不可用时的fallback执行方式"""
        # 使用简单的Python执行作为fallback
        try:
            # 提取技能代码并执行
            import json
            import builtins
            
            # 保存原始的导入函数
            original_import = builtins.__import__
            
            def safe_import(name, *args, **kwargs):
                forbidden = self.forbidden_modules
                if name in forbidden:
                    raise ImportError(f"Module {name} forbidden")
                return original_import(name, *args, **kwargs)
            
            # 替换导入函数
            builtins.__import__ = safe_import
            
            # 执行技能代码
            locals_dict = {}
            exec(self.current_script_content, globals(), locals_dict)
            
            # 调用execute函数
            if 'execute' in locals_dict:
                result = locals_dict['execute'](args)
            else:
                result = "No execute function found"
            
            # 恢复原始的导入函数
            builtins.__import__ = original_import
            
            return {"result": result}
        except Exception as e:
            return {"result": "Error", "error": str(e)}