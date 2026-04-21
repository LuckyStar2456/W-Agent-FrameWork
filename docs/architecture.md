# W-Agent 架构设计

## 一、整体架构

W-Agent 是一个基于 Python 的企业级智能体框架，采用模块化设计，支持 AOP、IOC、可观测性等企业级特性。

```
┌─────────────────────────────────────────────────────────────┐
│                      Application Layer                        │
├─────────────────────────────────────────────────────────────┤
│  Agent  │  Skills  │  Services  │  Controllers             │
├─────────────────────────────────────────────────────────────┤
│                      Core Framework                          │
├──────────┬──────────┬──────────┬──────────┬───────────────┤
│   AOP    │   IOC    │ Config   │ Resilience│ Observability │
├──────────┴──────────┴──────────┴──────────┴───────────────┤
│                    Infrastructure Layer                       │
├─────────────────────────────────────────────────────────────┤
│  Lifecycle  │  Scanner  │  Security  │  Distributed        │
└─────────────────────────────────────────────────────────────┘
```

## 二、核心模块

### 2.1 AOP（面向切面编程）

AOP 模块提供完整的切面编程支持，包括：

- **切点表达式解析**：支持 AspectJ 风格的切点表达式
  - `execution()` - 方法执行切点
  - `within()` - 类型匹配切点
  - `@annotation()` - 注解匹配切点
  - `bean()` - Bean 名称匹配
  - `args()` - 参数类型匹配

- **通知类型**：
  - `@Before` - 前置通知
  - `@After` - 后置通知
  - `@Around` - 环绕通知

- **切面实现**：
  - `RetryAspect` - 重试切面，支持指数退避
  - `CircuitBreakerAspect` - 断路器切面，支持 CLOSED/OPEN/HALF_OPEN 状态转换

```python
# 切点表达式示例
aspect = AspectJPointcut("execution(* com.example.*.*(..))")

# 使用重试切面
@Retry(max_attempts=3, delay=0.1, backoff=2.0)
async def unreliable_operation():
    pass
```

### 2.2 IOC（控制反转）

IOC 模块提供依赖注入容器，实现三级缓存解决循环依赖：

- **三级缓存机制**：
  - 一级缓存：`singleton_objects` - 完全成生的单例对象
  - 二级缓存：`early_singleton_objects` - 提前暴露的单例对象
  - 三级缓存：`singleton_factories` - 单例工厂

- **注入方式**：
  - 构造器注入
  - 字段注入（@Autowired）
  - Setter 注入（@Qualifier）

- **作用域**：
  - Singleton - 单例作用域
  - Prototype - 原型作用域

```python
# Bean 定义示例
bean_factory.register_bean_definition("user_service", BeanDefinition(
    name="user_service",
    bean_type=UserService,
    scope=Scope.SINGLETON,
    dependencies=["db_connection"]
))
```

### 2.3 配置管理

动态配置管理支持热更新：

- **配置绑定**：将配置值绑定到对象的属性
- **配置变更事件**：配置变更时自动通知监听器
- **多种配置源**：
  - 配置文件（JSON/YAML）
  - 环境变量
  - 代码配置

```python
# 配置绑定示例
config_manager.bind("api_key", service, "api_key")

# 配置变更监听
async def on_config_change(key, new_value, old_value):
    print(f"Config {key} changed from {old_value} to {new_value}")
```

### 2.4 弹性模式

提供重试和断路器等弹性模式：

- **重试策略**：
  - 最大重试次数
  - 初始延迟
  - 指数退避
  - 重试异常类型

- **断路器状态机**：
  - CLOSED - 正常状态
  - OPEN - 熔断状态
  - HALF_OPEN - 半开状态

```python
# 断路器示例
@CircuitBreaker(failure_threshold=5, recovery_timeout=30.0, fallback_method="fallback")
async def protected_operation():
    pass

async def fallback(*args, **kwargs):
    return "Fallback response"
```

### 2.5 可观测性

集成 OpenTelemetry 提供完整的可观测性支持：

- **链路追踪**：追踪请求在系统中的完整路径
- **指标监控**：收集和导出指标数据
- **健康检查**：检查系统各组件的健康状态

```python
# 开启追踪
tracer = global_tracer
with tracer.start_span("operation") as span:
    # 执行操作
    pass
```

### 2.6 沙箱安全

提供 Wasm 和 nsjail 两种沙箱隔离方案：

- **Wasm 沙箱**：
  - 使用 Pyodide 将 Python 编译为 Wasm
  - 安全的模块导入限制
  - 内存限制

- **nsjail 沙箱**：
  - seccomp 过滤
  - 资源限制（CPU、内存）
  - 能力禁用

## 三、生命周期管理

框架提供完整的生命周期管理：

1. **初始化阶段**：
   - 扫描组件
   - 注册 Bean
   - 执行依赖注入
   - 调用 @PostConstruct

2. **运行阶段**：
   - 处理请求
   - 事件驱动

3. **销毁阶段**：
   - 调用 @PreDestroy
   - 释放资源
   - 关闭连接

```python
class LifecycleOrder(IntEnum):
    INFRASTRUCTURE = 0    # 配置中心、日志、监控
    CONNECTION_POOL = 10  # 数据库、Redis 连接池
    REPOSITORY = 20       # 数据访问层
    SERVICE = 30          # 业务服务
    AGENT = 40            # Agent 组件
    PRESENTATION = 50     # 控制器、端点
```

## 四、分布式支持

- **分布式锁**：基于 Redis 的分布式锁实现
- **锁续期池**：自动续期防止锁过期
- **连接池管理**：Redis、MySQL 连接池

## 五、项目结构

```
w_agent/
├── aop/                    # 面向切面编程
│   ├── aspects.py          # 切面实现
│   ├── joinpoint.py        # 连接点
│   ├── pointcut.py         # 切点解析
│   └── proxy_factory.py    # 代理工厂
├── config/                 # 配置管理
│   └── dynamic_config.py   # 动态配置
├── container/              # 依赖注入容器
│   ├── bean_factory.py     # Bean 工厂
│   └── reflection_cache.py # 反射缓存
├── core/                   # 核心功能
│   ├── agent.py            # Agent 基类
│   ├── event_bus.py        # 事件总线
│   └── decorators.py       # 装饰器
├── lifecycle/              # 生命周期管理
│   ├── manager.py          # 生命周期管理器
│   └── order.py            # 生命周期顺序
├── observability/          # 可观测性
│   ├── tracing.py          # 链路追踪
│   ├── metrics.py          # 指标监控
│   └── health.py           # 健康检查
├── resilience/             # 弹性模式
│   ├── bulkhead.py         # 舱壁隔离
│   └── timeout.py          # 超时控制
├── scanner/                # AST 扫描
│   └── parallel_scanner.py # 并行扫描
├── skills/                 # 技能系统
│   └── sandbox/            # 沙箱
└── distributed/            # 分布式支持
    ├── lock.py             # 分布式锁
    └── lock_pool.py        # 锁续期池
```

## 六、设计原则

1. **模块化设计**：各模块职责明确，便于维护和扩展
2. **接口隔离**：使用抽象接口解耦具体实现
3. **依赖注入**：通过 IOC 容器管理依赖关系
4. **面向切面**：将横切关注点分离出来
5. **可配置性**：提供丰富的配置选项
6. **可观测性**：内置追踪、指标、日志支持
