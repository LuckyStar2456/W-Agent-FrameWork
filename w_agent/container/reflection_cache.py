import inspect
from typing import Dict, Callable, Any, List, Type
from typing import get_type_hints

class ReflectionCache:
    def __init__(self):
        self._signatures: Dict[Callable, inspect.Signature] = {}
        self._type_hints: Dict[Callable, Dict[str, type]] = {}
        self._class_attributes: Dict[Type, Dict[str, Any]] = {}
        self._class_methods: Dict[Type, List[str]] = {}
        self._class_annotations: Dict[Type, Dict[str, type]] = {}
    
    def get_signature(self, func: Callable) -> inspect.Signature:
        if func not in self._signatures:
            self._signatures[func] = inspect.signature(func)
        return self._signatures[func]
    
    def get_type_hints(self, func: Callable) -> Dict[str, type]:
        if func not in self._type_hints:
            self._type_hints[func] = get_type_hints(func)
        return self._type_hints[func]
    
    def get_class_attributes(self, cls: Type) -> Dict[str, Any]:
        if cls not in self._class_attributes:
            attributes = {}
            for name in dir(cls):
                if not name.startswith('__'):
                    try:
                        value = getattr(cls, name)
                        if not callable(value):
                            attributes[name] = value
                    except Exception:
                        pass
            self._class_attributes[cls] = attributes
        return self._class_attributes[cls]
    
    def get_class_methods(self, cls: Type) -> List[str]:
        if cls not in self._class_methods:
            methods = []
            for name, value in inspect.getmembers(cls, predicate=inspect.isfunction):
                if not name.startswith('__'):
                    methods.append(name)
            self._class_methods[cls] = methods
        return self._class_methods[cls]
    
    def get_class_annotations(self, cls: Type) -> Dict[str, type]:
        if cls not in self._class_annotations:
            annotations = {}
            if hasattr(cls, '__annotations__'):
                annotations = cls.__annotations__
            self._class_annotations[cls] = annotations
        return self._class_annotations[cls]

# 全局单例
_reflection_cache = ReflectionCache()