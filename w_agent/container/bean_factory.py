from typing import Dict, Any, List, Optional, Type, Callable
from pathlib import Path
from w_agent.lifecycle.manager import LifecycleManager
from w_agent.container.reflection_cache import _reflection_cache
from w_agent.observability.tracing import global_tracer
from w_agent.exceptions.framework_errors import BeanNotFoundError, InjectionError, CircularDependencyError
import asyncio
import inspect

class Scope:
    """Bean作用域"""
    SINGLETON = "singleton"
    PROTOTYPE = "prototype"

class BeanDefinition:
    """Bean定义"""
    def __init__(self, name: str, bean_type: Type, scope: str = Scope.SINGLETON, 
                 init_method: Optional[str] = None, destroy_method: Optional[str] = None,
                 dependencies: List[str] = None):
        self.name = name
        self.bean_type = bean_type
        self.scope = scope
        self.init_method = init_method
        self.destroy_method = destroy_method
        self.dependencies = dependencies or []

class BeanFactory:
    def __init__(self):
        # 三级缓存
        self._singleton_objects: Dict[str, Any] = {}  # 一级缓存：实例
        self._early_singleton_objects: Dict[str, Any] = {}  # 二级缓存：早期实例
        self._singleton_factories: Dict[str, Callable] = {}  # 三级缓存：工厂
        
        self._bean_definitions: Dict[str, BeanDefinition] = {}  # Bean定义
        self._lifecycle = LifecycleManager()
        self._graph = DependencyGraph()
    
    def register_bean_definition(self, name: str, definition: BeanDefinition):
        """注册Bean定义"""
        self._bean_definitions[name] = definition
        # 添加依赖关系到依赖图
        for dep in definition.dependencies:
            self._graph.add_dependency(name, dep)
    
    def register_bean(self, name: str, instance: Any, scope: str = Scope.SINGLETON):
        """直接注册Bean实例"""
        if scope == Scope.SINGLETON:
            self._singleton_objects[name] = instance
            self._lifecycle.register(instance)
    
    async def get_bean(self, name: str) -> Any:
        """获取Bean实例"""
        span = global_tracer.start_span("bean_factory.get_bean", attributes={"bean.name": name})
        try:
            # 先从一级缓存获取
            if name in self._singleton_objects:
                global_tracer.end_span(span)
                return self._singleton_objects[name]
            
            # 从二级缓存获取
            if name in self._early_singleton_objects:
                global_tracer.end_span(span)
                return self._early_singleton_objects[name]
            
            # 检查Bean定义是否存在
            if name not in self._bean_definitions and name not in self._singleton_objects:
                raise BeanNotFoundError(name)
            
            definition = self._bean_definitions[name]
            
            # 处理原型作用域
            if definition.scope == Scope.PROTOTYPE:
                instance = await self._create_bean(definition)
                global_tracer.end_span(span)
                return instance
            
            # 处理单例作用域，使用三级缓存解决循环依赖
            if name not in self._singleton_factories:
                # 创建Bean工厂
                async def factory():
                    return await self._create_bean(definition)
                
                self._singleton_factories[name] = factory
            
            # 从工厂创建实例
            instance = await self._singleton_factories[name]()
            
            # 移动到一级缓存
            self._singleton_objects[name] = instance
            self._early_singleton_objects.pop(name, None)
            self._singleton_factories.pop(name, None)
            
            # 注册到生命周期管理器
            self._lifecycle.register(instance)
            
            global_tracer.end_span(span)
            return instance
        except Exception as e:
            global_tracer.end_span(span)
            raise
    
    async def _create_bean(self, definition: BeanDefinition) -> Any:
        """创建Bean实例"""
        span = global_tracer.start_span("bean_factory.create_bean", attributes={"bean.name": definition.name, "bean.type": definition.bean_type.__name__})
        try:
            # 解析构造器参数
            constructor_args = await self._resolve_constructor_args(definition.bean_type)
            
            # 创建实例
            try:
                instance = definition.bean_type(**constructor_args)
            except Exception as e:
                raise InjectionError(f"Failed to create bean {definition.name}: {str(e)}")
            
            # 执行字段注入
            await self._inject_fields(instance)
            
            # 执行初始化方法
            if definition.init_method and hasattr(instance, definition.init_method):
                init_method = getattr(instance, definition.init_method)
                if asyncio.iscoroutinefunction(init_method):
                    await init_method()
                else:
                    init_method()
            
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
                        params = list(signature.parameters.values())[1:]  # 跳过self
                        if params:
                            param = params[0]
                            param_type = param.annotation
                            if param_type != inspect.Parameter.empty:
                                # 尝试根据类型获取Bean
                                bean_name = await self._find_bean_by_type(param_type)
                                if bean_name:
                                    bean_instance = await self.get_bean(bean_name)
                                    if asyncio.iscoroutinefunction(method):
                                        await method(bean_instance)
                                    else:
                                        method(bean_instance)
                                else:
                                    raise InjectionError(f"No bean found for setter method {method_name} parameter of type {param_type}")
        except Exception as e:
            raise InjectionError(f"Setter injection failed for {type(instance).__name__}: {str(e)}")
    
    async def _resolve_constructor_args(self, bean_type: Type) -> Dict[str, Any]:
        """解析构造器参数"""
        args = {}
        signature = _reflection_cache.get_signature(bean_type.__init__)
        
        for param_name, param in signature.parameters.items():
            if param_name == "self":
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
                        args[param_name] = await self.get_bean(qualifier_name)
                    else:
                        # 尝试按类型匹配
                        bean_name = await self._find_bean_by_type(param_type)
                        if bean_name:
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
            if issubclass(definition.bean_type, target_type):
                return bean_name
        
        # 尝试单例对象匹配
        for bean_name, instance in self._singleton_objects.items():
            if isinstance(instance, target_type):
                return bean_name
        
        return None
    
    async def destroy_singletons(self):
        # 获取所有单例 Bean 的销毁顺序（依赖者先销毁）
        order = self._graph.topological_sort(reverse=True)  # 依赖者在前
        for name in order:
            instance = self._singleton_objects.get(name)
            if instance:
                await self.pre_destroy_single(instance)
                del self._singleton_objects[name]
        
        # 清空缓存
        self._early_singleton_objects.clear()
        self._singleton_factories.clear()
    
    def create_snapshot(self, snapshot_path: Path):
        """创建BeanFactory快照"""
        import msgpack
        import zstd
        
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
                "dependencies": definition.dependencies
            }
        
        # 压缩并保存
        data = msgpack.packb(snapshot_data, use_bin_type=True)
        compressed = zstd.compress(data, level=3)
        snapshot_path.write_bytes(compressed)
    
    @classmethod
    def from_snapshot(cls, snapshot_path: Path):
        """从快照创建BeanFactory"""
        import msgpack
        import zstd
        
        # 读取并解压
        compressed = snapshot_path.read_bytes()
        data = zstd.decompress(compressed)
        snapshot_data = msgpack.unpackb(data)
        
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
                dependencies=def_data["dependencies"]
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
                    if asyncio.iscoroutinefunction(attr):
                        await attr()
                    else:
                        attr()
        except Exception as e:
            raise InjectionError(f"Pre-destroy failed for {type(instance).__name__}: {str(e)}")
    
    async def post_construct_all(self):
        """执行所有Bean的post_construct方法"""
        await self._lifecycle.post_construct_all()

class DependencyGraph:
    def __init__(self):
        self._dependencies: Dict[str, List[str]] = {}
    
    def add_dependency(self, bean: str, depends_on: str):
        self._dependencies.setdefault(bean, []).append(depends_on)
    
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

