import ast
from pathlib import Path

class MigrationTool:
    """迁移工具"""
    def upgrade(self, project_root: Path):
        """升级旧版代码到当前版本"""
        for py_file in project_root.rglob("*.py"):
            self._transform_file(py_file)
    
    def _transform_file(self, file_path: Path):
        """转换文件"""
        # 使用 AST 重写
        tree = ast.parse(file_path.read_text())
        transformer = AnnotationTransformer()
        new_tree = transformer.visit(tree)
        
        # 检查是否需要添加 import
        if not transformer.has_component_import:
            # 在文件开头添加 import
            import_stmt = ast.ImportFrom(
                module="w_agent.core.decorators",
                names=[ast.alias(name="Component", asname=None)],
                level=0
            )
            # 插入到文件开头
            new_tree.body.insert(0, import_stmt)
        
        file_path.write_text(ast.unparse(new_tree))

class AnnotationTransformer(ast.NodeTransformer):
    """注解转换器"""
    def __init__(self):
        self.has_component_import = False
    
    def visit_Module(self, node):
        """访问模块"""
        # 先检查是否已有 Component import
        for stmt in node.body:
            if isinstance(stmt, ast.ImportFrom):
                if stmt.module == "w_agent.core.decorators":
                    for alias in stmt.names:
                        if alias.name == "Component":
                            self.has_component_import = True
                            break
            if self.has_component_import:
                break
        
        # 继续访问其他节点
        return super().visit_Module(node)
    
    def visit_ClassDef(self, node):
        """访问类定义"""
        # 替换 @AgentComponent -> @Component
        new_decorators = []
        for decorator in node.decorator_list:
            decorator_name = self._get_decorator_name(decorator)
            if decorator_name == "AgentComponent":
                # 替换为 Component
                new_decorator = ast.Name(id="Component", ctx=ast.Load())
                if isinstance(decorator, ast.Call):
                    new_decorator = ast.Call(func=new_decorator, args=decorator.args, keywords=decorator.keywords)
                new_decorators.append(new_decorator)
            else:
                new_decorators.append(decorator)
        
        node.decorator_list = new_decorators
        return node
    
    def _get_decorator_name(self, decorator: ast.AST) -> str:
        """获取装饰器名称"""
        if isinstance(decorator, ast.Name):
            return decorator.id
        elif isinstance(decorator, ast.Attribute):
            return decorator.attr
        return ""
