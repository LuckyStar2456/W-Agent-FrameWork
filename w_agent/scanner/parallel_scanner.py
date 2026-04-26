import concurrent.futures
from pathlib import Path
import os
import ast
from typing import List, Any, Dict, Optional

class ComponentDef:
    """组件定义"""
    def __init__(self, name: str, component_type: str, class_name: Optional[str] = None, 
                 function_name: Optional[str] = None, file_path: Path = None, 
                 annotations: Dict[str, Any] = None):
        self.name = name
        self.component_type = component_type  # 'agent', 'service', 'tool', etc.
        self.class_name = class_name
        self.function_name = function_name
        self.file_path = file_path
        self.annotations = annotations or {}

class ScanResult:
    """扫描结果"""
    def __init__(self, components: List[ComponentDef]):
        self.components = components
    
    def to_dict(self):
        """转换为字典"""
        return {"components": [c.__dict__ for c in self.components]}
    
    @classmethod
    def from_dict(cls, data):
        """从字典创建"""
        components = []
        for c in data["components"]:
            # 处理Path对象的序列化问题
            if "file_path" in c and c["file_path"]:
                c["file_path"] = Path(c["file_path"])
            components.append(ComponentDef(**c))
        return cls(components)

class ParallelASTScanner:
    def __init__(self):
        self.component_decorators = [
            "AgentComponent",
            "ServiceComponent", 
            "ToolComponent",
            "RepositoryComponent",
            "ControllerComponent"
        ]
    
    def scan_package(self, package_path: Path, workers: int = 1) -> ScanResult:
        files = list(package_path.rglob("*.py"))
        print(f"Scanning files: {files}")
        all_components = []
        for file_path in files:
            components = self._scan_single_file(file_path)
            print(f"Found components in {file_path}: {components}")
            all_components.extend(components)
        # 合并结果
        print(f"Total components found: {len(all_components)}")
        return ScanResult(components=all_components)
    
    def _scan_single_file(self, file_path: Path) -> List[ComponentDef]:
        """扫描单个文件，解析AST并识别组件"""
        components = []
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            print(f"File content:\n{content}")
            
            tree = ast.parse(content, filename=str(file_path))
            
            # 扫描类定义
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    print(f"Found class: {node.name}")
                    print(f"Decorators: {[self._get_decorator_name(d) for d in node.decorator_list]}")
                    component = self._process_class_def(node, file_path)
                    if component:
                        components.append(component)
                        print(f"Found component: {component.name}")
                elif isinstance(node, ast.FunctionDef):
                    print(f"Found function: {node.name}")
                    print(f"Decorators: {[self._get_decorator_name(d) for d in node.decorator_list]}")
                    component = self._process_function_def(node, file_path)
                    if component:
                        components.append(component)
                        print(f"Found component: {component.name}")
        except Exception as e:
            # 忽略解析错误，继续扫描其他文件
            print(f"Error scanning file {file_path}: {e}")
            pass
        
        return components
    
    def _process_class_def(self, node: ast.ClassDef, file_path: Path) -> Optional[ComponentDef]:
        """处理类定义，识别组件注解"""
        for decorator in node.decorator_list:
            decorator_name = self._get_decorator_name(decorator)
            if decorator_name in self.component_decorators:
                # 提取注解参数
                annotations = self._extract_annotations(decorator)
                # 生成组件名称
                component_name = annotations.get('name', node.name.lower())
                # 确定组件类型
                component_type = decorator_name.replace('Component', '').lower()
                
                return ComponentDef(
                    name=component_name,
                    component_type=component_type,
                    class_name=node.name,
                    file_path=file_path,
                    annotations=annotations
                )
        return None
    
    def _process_function_def(self, node: ast.FunctionDef, file_path: Path) -> Optional[ComponentDef]:
        """处理函数定义，识别组件注解"""
        for decorator in node.decorator_list:
            decorator_name = self._get_decorator_name(decorator)
            if decorator_name in self.component_decorators:
                # 提取注解参数
                annotations = self._extract_annotations(decorator)
                # 生成组件名称
                component_name = annotations.get('name', node.name.lower())
                # 确定组件类型
                component_type = decorator_name.replace('Component', '').lower()
                
                return ComponentDef(
                    name=component_name,
                    component_type=component_type,
                    function_name=node.name,
                    file_path=file_path,
                    annotations=annotations
                )
        return None
    
    def _get_decorator_name(self, decorator: ast.AST) -> str:
        """获取装饰器名称"""
        if isinstance(decorator, ast.Name):
            return decorator.id
        elif isinstance(decorator, ast.Attribute):
            return decorator.attr
        elif isinstance(decorator, ast.Call):
            # 处理带参数的装饰器，如 @AgentComponent(name="test_agent")
            if isinstance(decorator.func, ast.Name):
                return decorator.func.id
            elif isinstance(decorator.func, ast.Attribute):
                return decorator.func.attr
        return ""
    
    def _extract_annotations(self, decorator: ast.AST) -> Dict[str, Any]:
        """提取装饰器参数"""
        annotations = {}
        
        def _eval_ast_node(node):
            """递归评估AST节点的值"""
            if isinstance(node, ast.Constant):
                return node.value
            elif isinstance(node, ast.Name):
                # 对于变量引用，返回变量名作为占位符
                return f"${node.id}"
            elif isinstance(node, ast.List):
                return [_eval_ast_node(element) for element in node.elts]
            elif isinstance(node, ast.Dict):
                return {_eval_ast_node(k): _eval_ast_node(v) for k, v in zip(node.keys, node.values)}
            elif isinstance(node, ast.Tuple):
                return tuple(_eval_ast_node(element) for element in node.elts)
            elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
                # 处理负数
                return -_eval_ast_node(node.operand)
            else:
                # 其他类型，返回字符串表示
                return str(node)
        
        if isinstance(decorator, ast.Call):
            # 处理位置参数
            for i, arg in enumerate(decorator.args):
                if i == 0:
                    annotations['name'] = _eval_ast_node(arg)
            
            # 处理关键字参数
            for kw in decorator.keywords:
                annotations[kw.arg] = _eval_ast_node(kw.value)
        
        return annotations