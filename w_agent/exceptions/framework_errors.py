class WAgentError(Exception):
    """所有框架异常的基类"""
    pass

class ContainerError(WAgentError):
    pass

class CircularDependencyError(ContainerError):
    def __init__(self, cycle: list):
        self.cycle = cycle
        super().__init__(f"Circular dependency detected: {' -> '.join(cycle)}")

class BeanNotFoundError(ContainerError):
    def __init__(self, bean_name: str):
        super().__init__(f"Bean not found: {bean_name}")

class InjectionError(ContainerError):
    def __init__(self, message: str):
        super().__init__(message)

class SecurityError(WAgentError):
    pass

class SkillSandboxError(SecurityError):
    def __init__(self, message: str):
        super().__init__(message)

class LLMTimeoutError(WAgentError):
    def __init__(self, message: str):
        super().__init__(message)