#!/usr/bin/env python3
"""W-Agent CLI工具"""

import argparse
import asyncio
import sys
from w_agent.container.bean_factory import BeanFactory
from w_agent.config.dynamic_config import DynamicConfigManager
from w_agent.core.doctor import Doctor


def get_version():
    """Return the installed distribution version, or the package version."""
    try:
        from importlib.metadata import version
        return version("wagent-framework")
    except Exception:
        from w_agent import __version__
        return __version__

def main():
    """CLI主函数"""
    parser = argparse.ArgumentParser(description='W-Agent Command Line Tool')
    parser.add_argument('-V', '--version', action='version',
                        version=f'W-Agent version {get_version()}')
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # health 命令
    health_parser = subparsers.add_parser('health', help='Check system health')
    subparsers.add_parser('doctor', help='Run detailed system diagnostics')
    
    # version 命令
    version_parser = subparsers.add_parser('version', help='Show version')
    
    # config 命令
    config_parser = subparsers.add_parser('config', help='Manage configuration')
    config_parser.add_argument('action', choices=['get', 'set', 'list'], help='Config action')
    config_parser.add_argument('key', nargs='?', help='Config key')
    config_parser.add_argument('value', nargs='?', help='Config value')
    
    # bean 命令
    bean_parser = subparsers.add_parser('bean', help='Manage beans')
    bean_parser.add_argument('action', choices=['list', 'info'], help='Bean action')
    bean_parser.add_argument('name', nargs='?', help='Bean name')
    
    args = parser.parse_args()
    
    if args.command in ('health', 'doctor'):
        return 0 if asyncio.run(check_health()) else 1
    elif args.command == 'version':
        show_version()
    elif args.command == 'config':
        asyncio.run(manage_config(args))
    elif args.command == 'bean':
        asyncio.run(manage_beans(args))
    else:
        parser.print_help()
    return 0

async def check_health():
    """检查系统健康状态"""
    print("Checking system health...")
    
    doctor = Doctor()
    results = doctor.run_all_checks()
    return doctor.print_results(results)

async def manage_config(args):
    """管理配置"""
    config = DynamicConfigManager()
    
    if args.action == 'list':
        print("Current configuration:")
        for key, value in config.as_dict().items():
            print(f"{key}: {value}")
    elif args.action == 'get':
        if not args.key:
            print("Error: Key is required for get action")
            return
        value = config.get(args.key)
        print(f"{args.key}: {value}")
    elif args.action == 'set':
        if not args.key or not args.value:
            print("Error: Key and value are required for set action")
            return
        config.set(args.key, args.value)
        print(f"Set {args.key} to {args.value}")

async def manage_beans(args):
    """管理Bean"""
    bean_factory = BeanFactory()
    
    if args.action == 'list':
        print("Registered beans:")
        for name in bean_factory.list_beans():
            print(f"- {name}")
    elif args.action == 'info':
        if not args.name:
            print("Error: Bean name is required for info action")
            return
        try:
            bean = await bean_factory.get_bean(args.name)
            print(f"Bean: {args.name}")
            print(f"Type: {type(bean).__name__}")
            print("Bean info retrieved successfully!")
        except Exception as e:
            print(f"Error: {e}")

def show_version():
    """显示版本信息"""
    print(f"W-Agent version {get_version()}")

if __name__ == '__main__':
    raise SystemExit(main())
