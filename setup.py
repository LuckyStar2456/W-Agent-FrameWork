from setuptools import setup, find_packages
import os

# 读取README.md作为长描述
here = os.path.abspath(os.path.dirname(__file__))
with open(os.path.join(here, "README.md"), "r", encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="wagent-framework",
    version="2.0.0a1",
    description="Open, composable Python framework for building agents",
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
        "redis",
        "packaging>=23",
        "pyyaml>=6",
        "typer>=0.12,<1",
        "rich>=13,<15",
    ],
    extras_require={
        "fastapi": ["fastapi", "uvicorn"],
        "langchain": ["langchain"],
        "models": ["httpx>=0.27,<1"],
        "mcp": ["httpx>=0.27,<1"],
        "tui": ["textual>=0.70,<9"],
        "wasm": ["wasmer-sdk>=0.1.2,<0.2; platform_system != 'Windows'"],
        "opentelemetry": [
            "opentelemetry-api",
            "opentelemetry-sdk",
            "opentelemetry-exporter-otlp",
        ],
        "testing": ["pytest", "pytest-asyncio"],
    },
    entry_points={
        "console_scripts": [
            "wagent=w_agent.cli:main",
            "w-agent=w_agent.cli:main",
        ]
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Topic :: Software Development :: Libraries :: Application Frameworks",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    python_requires=">=3.11",
    keywords="agent framework AOP IOC sandbox",
    project_urls={
        "Bug Reports": "https://github.com/LuckyStar2456/W-Agent-FrameWork/issues",
        "Source": "https://github.com/LuckyStar2456/W-Agent-FrameWork",
    },
)
