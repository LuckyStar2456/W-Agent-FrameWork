#!/usr/bin/env python3
"""
W-Agent 命令行工具
"""

import argparse
import asyncio
from pathlib import Path
from w_agent.scanner.parallel_scanner import ParallelASTScanner
from w_agent.container.bean_factory import BeanFactory
from w_agent.migration.migrate_previous import MigrationTool
from w_agent.core.doctor import Doctor

async def scan_command(directory):
    """扫描目录中的组件"""
    scanner = ParallelASTScanner()
    result = scanner.scan_package(Path(directory))
    
    print(f"Found {len(result.components)} components:")
    for component in result.components:
        print(f"- {component.name} ({component.component_type})")
        if component.class_name:
            print(f"  Class: {component.class_name}")
        if component.function_name:
            print(f"  Function: {component.function_name}")
        print(f"  File: {component.file_path}")

async def run_command(prompt):
    """运行默认Agent"""
    # 创建Bean工厂
    factory = BeanFactory()
    
    # 注册默认Agent
    class DefaultAgent:
        async def arun(self, prompt: str) -> str:
            return f"W-Agent: {prompt}"
    
    factory.register_bean("default_agent", DefaultAgent())
    
    # 获取并运行Agent
    agent = await factory.get_bean("default_agent")
    result = await agent.arun(prompt)
    print(result)

async def migrate_command(directory):
    """迁移旧版代码"""
    migration_tool = MigrationTool()
    migration_tool.upgrade(Path(directory))
    print(f"Migration completed for directory: {directory}")

async def server_command(host, port):
    """启动FastAPI服务器"""
    try:
        from w_agent.deployment.fastapi_depends import app
        import uvicorn
        
        print(f"Starting FastAPI server on {host}:{port}...")
        await uvicorn.run(app, host=host, port=port)
    except ImportError:
        print("FastAPI not installed. Please install with: pip install w-agent[fastapi]")

async def snapshot_command(output_path):
    """生成BeanFactory快照"""
    from w_agent.container.bean_factory import BeanFactory
    from w_agent.core.decorators import AgentComponent, ServiceComponent
    
    # 创建BeanFactory
    factory = BeanFactory()
    
    # 注册示例组件
    class TestService:
        def __init__(self):
            pass
    
    class TestAgent:
        def __init__(self, test_service: TestService):
            self.test_service = test_service
    
    # 注册Bean
    test_service = TestService()
    factory.register_bean("test_service", test_service)
    
    test_agent = TestAgent(test_service)
    factory.register_bean("test_agent", test_agent)
    
    # 生成快照
    output_path = Path(output_path)
    factory.create_snapshot(output_path)
    print(f"Snapshot created at: {output_path}")

async def doctor_command():
    """运行系统检查"""
    doctor = Doctor()
    results = doctor.run_all_checks()
    doctor.print_results(results)

async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="W-Agent Command Line Tool")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # 扫描命令
    scan_parser = subparsers.add_parser("scan", help="Scan directory for components")
    scan_parser.add_argument("directory", default=".", help="Directory to scan")
    
    # 运行命令
    run_parser = subparsers.add_parser("run", help="Run default agent with prompt")
    run_parser.add_argument("prompt", nargs="+", help="Prompt for the agent")
    
    # 迁移命令
    migrate_parser = subparsers.add_parser("migrate", help="Migrate old code to current version")
    migrate_parser.add_argument("directory", default=".", help="Directory to migrate")
    
    # 服务器命令
    server_parser = subparsers.add_parser("server", help="Start FastAPI server")
    server_parser.add_argument("--host", default="0.0.0.0", help="Host to bind")
    server_parser.add_argument("--port", type=int, default=8000, help="Port to bind")
    
    # 快照命令
    snapshot_parser = subparsers.add_parser("snapshot", help="Create BeanFactory snapshot")
    snapshot_parser.add_argument("output_path", default="./bean_factory.snapshot", help="Output snapshot path")
    
    # 检查命令
    doctor_parser = subparsers.add_parser("doctor", help="Check system components")
    
    args = parser.parse_args()
    
    if args.command == "scan":
        await scan_command(args.directory)
    elif args.command == "run":
        prompt = " ".join(args.prompt)
        await run_command(prompt)
    elif args.command == "migrate":
        await migrate_command(args.directory)
    elif args.command == "server":
        await server_command(args.host, args.port)
    elif args.command == "snapshot":
        await snapshot_command(args.output_path)
    elif args.command == "doctor":
        await doctor_command()
    else:
        parser.print_help()

if __name__ == "__main__":
    asyncio.run(main())
