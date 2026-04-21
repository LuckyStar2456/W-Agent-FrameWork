import tempfile
import subprocess
import os
import json
import sys
from typing import Dict, Any
from w_agent.skills.sandbox.wasm_sandbox import SkillSandbox

class NsJailSkillSandbox(SkillSandbox):
    def __init__(self, max_cpu_seconds: int = 5, max_memory_bytes: int = 1024 * 1024 * 100):
        self.max_cpu_seconds = max_cpu_seconds
        self.max_memory_bytes = max_memory_bytes
        self.nsjail_available = self._check_nsjail_availability()
    
    def _check_nsjail_availability(self) -> bool:
        """检查nsjail是否可用"""
        try:
            subprocess.run(["nsjail", "--version"], capture_output=True, check=True)
            return True
        except (subprocess.SubprocessError, FileNotFoundError):
            return False
    
    async def execute(self, skill: Any, script_name: str, args: Dict) -> Any:
        sandbox_root = None
        try:
            # 设置资源限制
            self._set_limits()
            
            sandbox_root = tempfile.TemporaryDirectory()
            
            # 1. 将技能代码复制到沙箱目录
            script_path = os.path.join(sandbox_root.name, script_name)
            with open(script_path, 'w', encoding='utf-8') as f:
                f.write(skill.scripts[script_name].read_text())
            
            # 2. 创建执行脚本
            exec_script = os.path.join(sandbox_root.name, "execute.py")
            with open(exec_script, 'w', encoding='utf-8') as f:
                f.write(f"""
import json
import sys

# 读取参数
args = json.loads(sys.argv[1])

# 执行技能代码
with open('{script_name}', 'r') as f:
    code = f.read()

exec_globals = dict()
exec_locals = {"args": args}
try:
    exec(code, exec_globals, exec_locals)
    result = exec_locals.get('result', 'Execution completed')
except Exception as e:
    result = f"Error: {str(e)}"

# 输出结果
print(json.dumps({"result": result}))
""".format(script_name=script_name))
            
            # 3. 执行代码
            if self.nsjail_available:
                result = await self._execute_with_nsjail(sandbox_root.name, exec_script, args)
            else:
                # Fallback to subprocess
                result = await self._execute_with_subprocess(sandbox_root.name, exec_script, args)
            
            return result
        finally:
            if sandbox_root:
                sandbox_root.cleanup()  # 确保删除
    
    async def _execute_with_nsjail(self, sandbox_root: str, exec_script: str, args: Dict) -> Any:
        """使用nsjail执行代码"""
        try:
            # 获取Python解释器路径
            python_executable = os.path.join(os.path.dirname(sys.executable), "python3")
            if not os.path.exists(python_executable):
                python_executable = "python3"  # 回退到系统python3
            
            # 构建nsjail命令，添加更多安全配置
            cmd = [
                "nsjail",
                "--mode", "o",
                "--chroot", sandbox_root,
                "--time_limit", str(self.max_cpu_seconds),
                "--memory_limit", str(self.max_memory_bytes // 1024),  # 单位为KB
                "--disable_clone_newcgroup",
                "--seccomp_string", "DEFAULT",  # 使用默认的seccomp过滤
                "--seccomp_log", "1",  # 启用seccomp日志
                "--capability", "none",  # 禁用所有capabilities
                "--disable_proc",  # 禁用/proc
                "--disable_dev",  # 禁用/dev
                "--",
                python_executable, exec_script, json.dumps(args)
            ]
            
            # 执行命令
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=sandbox_root,
                timeout=self.max_cpu_seconds + 2
            )
            
            # 解析结果
            if result.returncode == 0 and result.stdout:
                try:
                    return json.loads(result.stdout)
                except json.JSONDecodeError:
                    return {"result": result.stdout.strip()}
            else:
                return {"result": "Error", "error": result.stderr.strip()}
        except Exception as e:
            return {"result": "Error", "error": str(e)}
    
    async def _execute_with_subprocess(self, sandbox_root: str, exec_script: str, args: Dict) -> Any:
        """使用subprocess执行代码（fallback）"""
        try:
            # 构建subprocess命令
            cmd = [
                "python3", exec_script, json.dumps(args)
            ]
            
            # 执行命令
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=sandbox_root,
                timeout=self.max_cpu_seconds + 2
            )
            
            # 解析结果
            if result.returncode == 0 and result.stdout:
                try:
                    return json.loads(result.stdout)
                except json.JSONDecodeError:
                    return {"result": result.stdout.strip()}
            else:
                return {"result": "Error", "error": result.stderr.strip()}
        except Exception as e:
            return {"result": "Error", "error": str(e)}
    
    def _set_limits(self):
        """设置资源限制"""
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (self.max_cpu_seconds, self.max_cpu_seconds))
        resource.setrlimit(resource.RLIMIT_AS, (self.max_memory_bytes, self.max_memory_bytes))