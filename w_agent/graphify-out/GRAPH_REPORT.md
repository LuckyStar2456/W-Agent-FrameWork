# Graph Report - w_agent  (2026-06-15)

## Corpus Check
- 55 files · ~9,559 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 449 nodes · 757 edges · 39 communities (34 shown, 5 thin omitted)
- Extraction: 80% EXTRACTED · 20% INFERRED · 0% AMBIGUOUS · INFERRED: 153 edges (avg confidence: 0.56)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `985c404a`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]

## God Nodes (most connected - your core abstractions)
1. `BeanFactory` - 29 edges
2. `Event` - 21 edges
3. `EventBus` - 21 edges
4. `Doctor` - 20 edges
5. `LifecycleManager` - 16 edges
6. `InjectionError` - 15 edges
7. `AopProxy` - 13 edges
8. `ResilienceManager` - 13 edges
9. `DynamicConfigManager` - 12 edges
10. `ToolComponent` - 12 edges

## Surprising Connections (you probably didn't know these)
- `DefaultAgent` --uses--> `BeanFactory`  [INFERRED]
  __main__.py → container/bean_factory.py
- `main()` --calls--> `BeanFactory`  [INFERRED]
  __main__.py → container/bean_factory.py
- `RetryAspect` --uses--> `Event`  [INFERRED]
  aop/aspects.py → core/event_bus.py
- `RetryAspect` --uses--> `EventBus`  [INFERRED]
  aop/aspects.py → core/event_bus.py
- `EventBus` --uses--> `Event`  [INFERRED]
  aop/aspects.py → core/event_bus.py

## Import Cycles
- 1-file cycle: `deployment/fastapi_depends.py -> deployment/fastapi_depends.py`

## Communities (39 total, 5 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.06
Nodes (17): CircuitBreakerAspect, EventBus, RetryAspect, JoinPoint, 连接点抽象，支持 proceed 链式调用, Advice, AfterAdvice, AroundAdvice (+9 more)

### Community 1 - "Community 1"
Cohesion: 0.10
Nodes (18): BeanDefinition, BeanFactory, DependencyGraph, Any, Path, 根据类型查找Bean，支持接口/抽象基类匹配, 执行所有Bean的post_construct方法, Scope (+10 more)

### Community 2 - "Community 2"
Cohesion: 0.12
Nodes (19): BaseException, ToolComponent, ConfigChangedEvent, Event, EventBus, Any, AsyncCallbackHandler, BaseModel (+11 more)

### Community 3 - "Community 3"
Cohesion: 0.10
Nodes (10): Doctor, NsJailSkillSandbox, 使用subprocess执行代码（fallback）, 使用Pyodide编译Python代码为Wasm, 当Wasm不可用时的fallback执行方式, SkillSandbox, WasmSkillSandbox, Any (+2 more)

### Community 4 - "Community 4"
Cohesion: 0.09
Nodes (15): ABC, BaseAgent, chat(), FastAPIContext, get_agent(), graceful_shutdown_middleware(), lifespan(), FastAPI 依赖项，从容器获取 Agent (+7 more)

### Community 5 - "Community 5"
Cohesion: 0.14
Nodes (11): ClassDef, FunctionDef, Path, ScannerCache, ComponentDef, ParallelASTScanner, Any, AST (+3 more)

### Community 6 - "Community 6"
Cohesion: 0.12
Nodes (12): BaseAgent, check_health(), main(), manage_beans(), manage_config(), show_version(), DynamicConfigManager, Any (+4 more)

### Community 7 - "Community 7"
Cohesion: 0.10
Nodes (11): AgentComponent, Autowired, Component, ControllerComponent, PostConstruct, PreDestroy, Any, Qualifier (+3 more)

### Community 8 - "Community 8"
Cohesion: 0.14
Nodes (8): AuthProvider, Identity, JSONRPCRequest, JwtAuthProvider, McpAuthMiddleware, McpTransport, Any, RevocationList

### Community 9 - "Community 9"
Cohesion: 0.23
Nodes (6): SkillLoadError, Any, Path, Skill, SkillLoader, SkillRegistry

### Community 10 - "Community 10"
Cohesion: 0.18
Nodes (3): LockRenewalPool, RedisDistributedLock, RedisDistributedLock

### Community 12 - "Community 12"
Cohesion: 0.27
Nodes (4): AnnotationTransformer, MigrationTool, AST, Path

### Community 13 - "Community 13"
Cohesion: 0.20
Nodes (3): Any, ReflectionCache, Signature

### Community 14 - "Community 14"
Cohesion: 0.27
Nodes (6): Exception, call_with_timeout(), LLMTimeoutError, Path, SecurityError, SkillVerifier

### Community 15 - "Community 15"
Cohesion: 0.33
Nodes (5): IntEnum, Any, LifecycleOrder, 生命周期执行顺序（数值越小越先初始化，越后销毁）, LifecycleOrder

### Community 16 - "Community 16"
Cohesion: 0.29
Nodes (3): add_otel_context(), LogEnable, 添加OpenTelemetry上下文到日志

## Knowledge Gaps
- **9 isolated node(s):** `Pattern`, `Signature`, `Any`, `Any`, `Any` (+4 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **5 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Doctor` connect `Community 3` to `Community 0`, `Community 1`, `Community 2`, `Community 4`, `Community 6`, `Community 10`?**
  _High betweenness centrality (0.337) - this node is a cross-community bridge._
- **Why does `BeanFactory` connect `Community 1` to `Community 3`, `Community 4`, `Community 6`?**
  _High betweenness centrality (0.235) - this node is a cross-community bridge._
- **Why does `ResilienceManager` connect `Community 0` to `Community 3`?**
  _High betweenness centrality (0.155) - this node is a cross-community bridge._
- **Are the 14 inferred relationships involving `BeanFactory` (e.g. with `manage_beans()` and `BeanNotFoundError`) actually correct?**
  _`BeanFactory` has 14 INFERRED edges - model-reasoned connections that need verification._
- **Are the 16 inferred relationships involving `Event` (e.g. with `CircuitBreakerAspect` and `EventBus`) actually correct?**
  _`Event` has 16 INFERRED edges - model-reasoned connections that need verification._
- **Are the 14 inferred relationships involving `EventBus` (e.g. with `CircuitBreakerAspect` and `EventBus`) actually correct?**
  _`EventBus` has 14 INFERRED edges - model-reasoned connections that need verification._
- **Are the 8 inferred relationships involving `Doctor` (e.g. with `DynamicConfigManager` and `BeanFactory`) actually correct?**
  _`Doctor` has 8 INFERRED edges - model-reasoned connections that need verification._