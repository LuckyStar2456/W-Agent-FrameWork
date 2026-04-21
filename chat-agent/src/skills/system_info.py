#!/usr/bin/env python3
"""
系统信息技能
"""
import os
import platform
import sys
import datetime

def execute(params):
    """执行系统信息查询"""
    info_type = params.get("type", "all")
    
    if info_type == "all":
        return get_all_info()
    elif info_type == "os":
        return get_os_info()
    elif info_type == "python":
        return get_python_info()
    elif info_type == "time":
        return get_current_time()
    elif info_type == "date":
        return get_current_date()
    else:
        return f"未知的信息类型: {info_type}"

def get_all_info():
    """获取所有系统信息"""
    os_info = get_os_info()
    python_info = get_python_info()
    time_info = get_current_time()
    date_info = get_current_date()
    
    return f"系统信息:\n{os_info}\n{python_info}\n{time_info}\n{date_info}"

def get_os_info():
    """获取操作系统信息"""
    try:
        system = platform.system()
        release = platform.release()
        version = platform.version()
        machine = platform.machine()
        
        return f"操作系统: {system} {release} ({version}), 架构: {machine}"
    except Exception as e:
        return f"获取操作系统信息失败: {str(e)}"

def get_python_info():
    """获取Python信息"""
    try:
        version = sys.version
        return f"Python版本: {version}"
    except Exception as e:
        return f"获取Python信息失败: {str(e)}"

def get_current_time():
    """获取当前时间"""
    try:
        current_time = datetime.datetime.now().strftime("%H:%M:%S")
        return f"当前时间: {current_time}"
    except Exception as e:
        return f"获取当前时间失败: {str(e)}"

def get_current_date():
    """获取当前日期"""
    try:
        current_date = datetime.datetime.now().strftime("%Y-%m-%d")
        return f"当前日期: {current_date}"
    except Exception as e:
        return f"获取当前日期失败: {str(e)}"
