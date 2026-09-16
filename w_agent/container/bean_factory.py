from typing import Dict, Any, List, Optional, Type, Callable
from pathlib import Path
from w_agent.lifecycle.manager import LifecycleManager
from w_agent.lifecycle.order import LifecycleOrder
from w_agent.container.reflection_cache import _reflection_cache
from w_agent.observability.tracing import global_tracer
from w_agent.exceptions.framework_errors import BeanNotFoundError, InjectionError, CircularDependencyError
import asyncio
import contextvars
import inspect

class Scope:
    """Bean作用域"""
    SINGLETON = "singleton"
    PROTOTYPE = "prototype"

class BeanDefinition:
    """Bean定义"""
    def __init__(self, name: str, bean_type: Type, scope: str = Scope.SINGLETON, 
                 init_method: Optional[str] = None, destroy_method: Optional[str] = None,
                 dependencies: List[str] = None,
                 lifecycle_order: LifecycleOrder = LifecycleOrder.SERVICE):
        self.name = name
        self.bean_type = bean_type
        self.scope = scope
        self.init_method = init_method
        self.destroy_method = destroy_method
        self.dependencies = dependencies or []
        self.lifecycle_order = lifecycle_order

class BeanFactory:
    def __init__(self):
        # 三级缓存
        self._singleton_objects: Dict[str, Any] = {}  # 一级缓存：实例
        self._early_singleton_objects: Dict[str, Any] = {}  # 二级缓存：早期实例
        self._singleton_factories: Dict[str, Callable] = {}  # 三级缓存：工厂
        
        self._bean_definitions: Dict[str, BeanDefinition] = {}  # Bean定义
        self._lifecycle = LifecycleManager()
        self._graph = DependencyGraph()
        self._creation_locks: Dict[str, asyncio.Lock] = {}
        self._creation_stack = contextvars.ContextVar(
            f"w_agent_creation_stack_{id(self)}", default=()
        )
    
    def register_bean_definition(self, name: str, definition: BeanDefinition):
        """注册Bean定义"""
        if not name or not isinstance(name, str):
            raise InjectionError("Bean name must be a non-empty string")
        
        definition.name = name
        self._bean_definitions[name] = definition
        self._graph.add_node(name)
        # 添加依赖关系到依赖图
        if definition.dependencies:
            for dep in definition.dependencies:
                if dep and isinstance(dep, str):
                    self._graph.add_dependency(name, dep)
    
    def register_bean(
        self,
        name: str,
        instance: Any,
        scope: str = Scope.SINGLETON,
        lifecycle_order: LifecycleOrder = LifecycleOrder.SERVICE,
    ):
        """直接注册Bean实例"""
        if scope == Scope.SINGLETON:
            self._singleton_objects[name] = instance
            self._graph.add_node(name)
            self._lifecycle.register(instance, lifecycle_order)
    
    async def get_bean(self, name: str) -> Any:
        """获取Bean实例"""
        span = global_tracer.start_span("bean_factory.get_bean", attributes={"bean.name": name})
        try:
            if name in self._singleton_objects:
                return self._singleton_objects[name]
            stack = self._creation_stack.get()
            if name in self._early_singleton_objects and name in stack:
                return self._early_singleton_objects[name]

            if name not in self._bean_definitions:
                raise BeanNotFoundError(name)
            definition = self._bean_definitions[name]

            if definition.scope == Scope.PROTOTYPE:
                return await self._create_bean(definition)

            if name in stack:
                cycle_start = stack.index(name)
                raise CircularDependencyError(list(stack[cycle_start:]) + [name])

            lock = self._creation_locks.setdefault(name, asyncio.Lock())
            async with lock:
                if name in self._singleton_objects:
                    return self._singleton_objects[name]

                stack = self._creation_stack.get()
                if name in stack:
                    cycle_start = stack.index(name)
                    raise CircularDependencyError(list(stack[cycle_start:]) + [name])
                token = self._creation_stack.set(stack + (name,))
                try:
                    async def factory():
                        return await self._create_bean(definition)

                    self._singleton_factories[name] = factory
                    instance = await factory()
                    self._singleton_objects[name] = instance
                    self._early_singleton_objects.pop(name, None)
                    self._singleton_factories.pop(name, None)
                    self._lifecycle.register(instance, definition.lifecycle_order)
                    return instance
                except Exception:
                    self._early_singleton_objects.pop(name, None)
                    self._singleton_factories.pop(name, None)
                    raise
                finally:
                    self._creation_stack.reset(token)
        finally:
            global_tracer.end_span(span)
    
    async def _create_bean(self, definition: BeanDefinition) -> Any:
        """创建Bean实例"""
        span = global_tracer.start_span("bean_factory.create_bean", attributes={"bean.name": definition.name, "bean.type": definition.bean_type.__name__})
        try:
            # 解析构造器参数
            constructor_args = await self._resolve_constructor_args(definition)
            
            # 创建实例
            try:
                instance = definition.bean_type(**constructor_args)
            except Exception as e:
                raise InjectionError(f"Failed to create bean {definition.name}: {str(e)}")

            if definition.scope == Scope.SINGLETON:
                self._early_singleton_objects[definition.name] = instance

            # 执行字段注入
            await self._inject_fields(instance)
            
            # 执行初始化方法
            if definition.init_method and hasattr(instance, definition.init_method):
                init_method = getattr(instance, definition.init_method)
                result = init_method()
                if inspect.isawaitable(result):
                    await result
            
            global_tracer.end_span(span)
            return instance
        except Exception as e:
            global_tracer.end_span(span)
            raise
    
    async def _inject_fields(self, instance: Any):
        """执行字段注入"""
        try:
            # 检查类的注解
            if hasattr(instance.__class__, "__annotations__"):
                for field_name, field_type in instance.__class__.__annotations__.items():
                    # 检查字段是否有@Autowired注解
                    if hasattr(instance.__class__, field_name):
                        field = getattr(instance.__class__, field_name)
                        if hasattr(field, "__autowired__"):
                            # 获取@Autowired指定的名称
                            autowired_name = getattr(field, "__autowired_name__", None)
                            if autowired_name:
                                # 使用指定的Bean名称
                                bean_instance = await self.get_bean(autowired_name)
                                setattr(instance, field_name, bean_instance)
                            else:
                                # 尝试根据类型获取Bean
                                bean_name = await self._find_bean_by_type(field_type)
                                if bean_name:
                                    bean_instance = await self.get_bean(bean_name)
                                    setattr(instance, field_name, bean_instance)
                                else:
                                    raise InjectionError(f"No bean found for field {field_name} of type {field_type}")
            
            # 执行setter注入
            await self._inject_setters(instance)
        except Exception as e:
            raise InjectionError(f"Field injection failed for {type(instance).__name__}: {str(e)}")
    
    async def _inject_setters(self, instance: Any):
        """执行setter注入"""
        try:
            # 检查所有setter方法
            for method_name in dir(instance):
                if method_name.startswith("set") and len(method_name) > 3:
                    method = getattr(instance, method_name)
                    if callable(method) and hasattr(method, "__autowired__"):
                        # 获取方法参数
                        signature = _reflection_cache.get_signature(method)
                        # inspect.signature(bound_method) already omits self.
                        params = list(signature.parameters.values())
                        if params:
                            param = params[0]
                            param_type = param.annotation
                            if param_type != inspect.Parameter.empty:
                                # 尝试根据类型获取Bean
                                bean_name = await self._find_bean_by_type(param_type)
                                if bean_name:
                                    bean_instance = await self.get_bean(bean_name)
                                    result = method(bean_instance)
                                    if inspect.isawaitable(result):
                                        await result
                                else:
                                    raise InjectionError(f"No bean found for setter method {method_name} parameter of type {param_type}")
        except Exception as e:
            raise InjectionError(f"Setter injection failed for {type(instance).__name__}: {str(e)}")
    
    async def _resolve_constructor_args(self, definition: BeanDefinition) -> Dict[str, Any]:
        """解析构造器参数"""
        args = {}
        bean_type = definition.bean_type
        signature = _reflection_cache.get_signature(bean_type.__init__)
        
        for param_name, param in signature.parameters.items():
            if param_name == "self":
                continue
            if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                continue
            
            # 检查是否有@Qualifier注解
            qualifier_name = None
            # 检查参数级别的@Qualifier注解
            if hasattr(bean_type.__init__, f"__qualifier_{param_name}__"):
                qualifier_name = getattr(bean_type.__init__, f"__qualifier_{param_name}__")
            # 检查方法级别的@Qualifier注解
            elif hasattr(bean_type.__init__, "__qualifier__"):
                qualifier_name = getattr(bean_type.__init__, "__qualifier__")
            
            # 检查是否有@Autowired注解
            autowired = False
            if hasattr(bean_type.__init__, f"__autowired_{param_name}__"):
                autowired = getattr(bean_type.__init__, f"__autowired_{param_name}__")
            elif hasattr(bean_type.__init__, "__autowired__"):
                autowired = getattr(bean_type.__init__, "__autowired__")
            
            # 尝试根据类型获取Bean
            param_type = param.annotation
            if param_type != inspect.Parameter.empty:
                try:
                    # 如果有@Qualifier注解，直接使用指定的Bean名称
                    if qualifier_name:
                        self._graph.add_dependency(definition.name, qualifier_name)
                        args[param_name] = await self.get_bean(qualifier_name)
                    else:
                        # 尝试按类型匹配
                        bean_name = await self._find_bean_by_type(param_type)
                        if bean_name:
                            self._graph.add_dependency(definition.name, bean_name)
                            args[param_name] = await self.get_bean(bean_name)
                        else:
                            # 如果找不到Bean，使用默认值
                            if param.default != inspect.Parameter.empty:
                                args[param_name] = param.default
                            else:
                                raise InjectionError(f"No bean found for parameter {param_name} of type {param_type}")
                except BeanNotFoundError:
                    # 如果找不到Bean，使用默认值
                    if param.default != inspect.Parameter.empty:
                        args[param_name] = param.default
                    else:
                        raise InjectionError(f"No bean found for parameter {param_name} of type {param_type}")
            else:
                # 无类型注解，使用默认值
                if param.default != inspect.Parameter.empty:
                    args[param_name] = param.default
                else:
                    raise InjectionError(f"Parameter {param_name} has no type annotation and no default value")
        
        return args
    
    async def _find_bean_by_type(self, target_type: Type) -> Optional[str]:
        """根据类型查找Bean，支持接口/抽象基类匹配"""
        # 首先尝试完全匹配
        for bean_name, definition in self._bean_definitions.items():
            if definition.bean_type == target_type:
                return bean_name
        
        # 尝试接口/抽象基类匹配
        for bean_name, definition in self._bean_definitions.items():
            try:
                if issubclass(definition.bean_type, target_type):
                    return bean_name
            except TypeError:
                continue
        
        # 尝试单例对象匹配
        for bean_name, instance in self._singleton_objects.items():
            try:
                if isinstance(instance, target_type):
                    return bean_name
            except TypeError:
                continue
        
        return None
    
    async def destroy_singletons(self):
        # 获取所有单例 Bean 的销毁顺序（依赖者先销毁）
        order = self._graph.topological_sort(reverse=True)  # 依赖者在前
        order.extend(name for name in self._singleton_objects if name not in order)
        for name in order:
            instance = self._singleton_objects.get(name)
            if instance:
                definition = self._bean_definitions.get(name)
                if definition and definition.destroy_method:
                    destroy_method = getattr(instance, definition.destroy_method, None)
                    if destroy_method and not hasattr(destroy_method, "__pre_destroy__"):
                        result = destroy_method()
                        if inspect.isawaitable(result):
                            await result
                await self.pre_destroy_single(instance)
                del self._singleton_objects[name]
        
        # 清空缓存
        self._early_singleton_objects.clear()
        self._singleton_factories.clear()
    
    def create_snapshot(self, snapshot_path: Path):
        """创建BeanFactory快照"""
        import msgpack
        import zstandard
        
        # 序列化BeanDefinition
        snapshot_data = {
            "bean_definitions": {}
        }
        
        for name, definition in self._bean_definitions.items():
            snapshot_data["bean_definitions"][name] = {
                "name": definition.name,
                "bean_type": f"{definition.bean_type.__module__}.{definition.bean_type.__name__}",
                "scope": definition.scope,
                "init_method": definition.init_method,
                "destroy_method": definition.destroy_method,
                "dependencies": definition.dependencies,
                "lifecycle_order": int(definition.lifecycle_order),
            }
        
        # 压缩并保存
        data = msgpack.packb(snapshot_data, use_bin_type=True)
        compressed = zstandard.ZstdCompressor(level=3).compress(data)
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_bytes(compressed)
    
    @classmethod
    def from_snapshot(cls, snapshot_path: Path):
        """从快照创建BeanFactory"""
        import msgpack
        import zstandard
        
        # 读取并解压
        compressed = snapshot_path.read_bytes()
        data = zstandard.ZstdDecompressor().decompress(compressed)
        snapshot_data = msgpack.unpackb(data, raw=False)
        
        # 创建BeanFactory
        factory = cls()
        
        # 恢复BeanDefinition
        for name, def_data in snapshot_data["bean_definitions"].items():
            # 动态导入类型
            module_name, class_name = def_data["bean_type"].rsplit(".", 1)
            module = __import__(module_name, fromlist=[class_name])
            bean_type = getattr(module, class_name)
            
            # 创建BeanDefinition
            definition = BeanDefinition(
                name=def_data["name"],
                bean_type=bean_type,
                scope=def_data["scope"],
                init_method=def_data["init_method"],
                destroy_method=def_data["destroy_method"],
                dependencies=def_data["dependencies"],
                lifecycle_order=LifecycleOrder(
                    def_data.get("lifecycle_order", int(LifecycleOrder.SERVICE))
                ),
            )
            factory.register_bean_definition(name, definition)
        
        return factory
    
    async def pre_destroy_single(self, instance: Any):
        """执行单个实例的销毁方法"""
        try:
            # 执行单个实例的销毁方法
            for name in dir(instance):
                attr = getattr(instance, name)
                if hasattr(attr, "__pre_destroy__"):
                    result = attr()
                    if inspect.isawaitable(result):
                        await result
        except Exception as e:
            raise InjectionError(f"Pre-destroy failed for {type(instance).__name__}: {str(e)}")
    
    async def post_construct_all(self):
        """执行所有Bean的post_construct方法"""
        await self._lifecycle.post_construct_all()

    def list_beans(self) -> List[str]:
        """List registered definitions and instantiated singletons."""
        return sorted(set(self._bean_definitions) | set(self._singleton_objects))

    def scan_and_register(self, package_path: Path):
        """Discover decorated components and register them with this factory.

        Modules are loaded from their file paths. Applications that require
        package-relative imports should import those modules normally before
        calling this helper.
        """
        import importlib.util
        import sys
        from w_agent.scanner.parallel_scanner import ParallelASTScanner

        package_path = Path(package_path).resolve()
        scan_result = ParallelASTScanner().scan_package(package_path)
        modules = {}
        discovered = []
        order_by_type = {
            "repository": LifecycleOrder.REPOSITORY,
            "service": LifecycleOrder.SERVICE,
            "agent": LifecycleOrder.AGENT,
            "controller": LifecycleOrder.PRESENTATION,
            "tool": LifecycleOrder.SERVICE,
        }

        for component in scan_result.components:
            file_path = Path(component.file_path).resolve()
            module = modules.get(file_path)
            if module is None:
                module_name = f"w_agent_scanned_{abs(hash(file_path))}"
                module = sys.modules.get(module_name)
                if module is None:
                    spec = importlib.util.spec_from_file_location(module_name, file_path)
                    if spec is None or spec.loader is None:
                        raise InjectionError(f"Unable to load component module: {file_path}")
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = module
                    spec.loader.exec_module(module)
                modules[file_path] = module

            attribute_name = component.class_name or component.function_name
            target = getattr(module, attribute_name)
            lifecycle_order = order_by_type.get(
                component.component_type, LifecycleOrder.SERVICE
            )
            if inspect.isclass(target):
                self.register_bean_definition(
                    component.name,
                    BeanDefinition(
                        component.name,
                        target,
                        lifecycle_order=lifecycle_order,
                    ),
                )
            else:
                self.register_bean(
                    component.name,
                    target,
                    lifecycle_order=lifecycle_order,
                )
            discovered.append(component.name)
        return discovered

    async def initialize_singletons(self):
        """Instantiate all singleton definitions and run lifecycle initializers."""
        for name, definition in list(self._bean_definitions.items()):
            if definition.scope == Scope.SINGLETON:
                await self.get_bean(name)
        await self.post_construct_all()

class DependencyGraph:
    def __init__(self):
        self._dependencies: Dict[str, List[str]] = {}
    
    def add_dependency(self, bean: str, depends_on: str):
        self.add_node(bean)
        self.add_node(depends_on)
        self._dependencies.setdefault(bean, []).append(depends_on)

    def add_node(self, bean: str):
        self._dependencies.setdefault(bean, [])
    
    def topological_sort(self, reverse: bool = False) -> List[str]:
        # 简单的拓扑排序实现
        visited = set()
        temp = set()
        result = []
        
        def visit(node):
            if node in temp:
                raise CircularDependencyError([node])
            if node not in visited:
                temp.add(node)
                for dep in self._dependencies.get(node, []):
                    visit(dep)
                temp.remove(node)
                visited.add(node)
                result.append(node)
        
        for node in self._dependencies:
            if node not in visited:
                visit(node)
        
        if reverse:
            result.reverse()
        return result

