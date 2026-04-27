from setuptools import setup, find_packages
import os

# 读取README.md作为长描述
here = os.path.abspath(os.path.dirname(__file__))
with open(os.path.join(here, 'README.md'), 'r', encoding='utf-8') as f:
    long_description = f.read()

setup(
    name="wagent-framework",
    version="1.5.0",
    description="Python enterprise agent framework with AOP, IOC, and sandbox security",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/LuckyStar2456/W-Agent-FrameWork",
    author="LuckyStar2456",
    author_email="lucky_star_2456@example.com",
    license="MIT",
    packages=find_packages(),
    install_requires=[
        "pydantic",
        "structlog",
        "cryptography",
        "msgpack",
        "zstandard",
        "pyjwt",
        "asgiref",
        "redis"
    ],
    extras_require={
        "fastapi": ["fastapi", "uvicorn"],
        "langchain": ["langchain"],
        "wasm": ["wasmer"],
        "opentelemetry": ["opentelemetry-api", "opentelemetry-sdk", "opentelemetry-exporter-otlp"],
        "testing": ["pytest", "pytest-asyncio"]
    },
    entry_points={
        "console_scripts": [
            "w-agent=w_agent.cli:main"
        ]
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Libraries :: Application Frameworks",
        "Topic :: Software Development :: Libraries :: Python Modules"
    ],
    python_requires=">=3.9",
    keywords="agent framework AOP IOC sandbox",
    project_urls={
        "Bug Reports": "https://github.com/LuckyStar2456/W-Agent-FrameWork/issues",
        "Source": "https://github.com/LuckyStar2456/W-Agent-FrameWork",
    },
)
