from enum import IntEnum

class LifecycleOrder(IntEnum):
    """生命周期执行顺序（数值越小越先初始化，越后销毁）"""
    INFRASTRUCTURE = 0    # 配置中心、日志、监控
    CONNECTION_POOL = 10  # 数据库、Redis 连接池
    REPOSITORY = 20       # 数据访问层
    SERVICE = 30          # 业务服务
    AGENT = 40            # Agent 组件
    PRESENTATION = 50     # 控制器、端点