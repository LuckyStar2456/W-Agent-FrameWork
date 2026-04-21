from setuptools import setup, find_packages

setup(
    name="w-agent",
    version="1.4.0",
    packages=find_packages(),
    install_requires=[
        "pydantic",
        "structlog",
        "cryptography",
        "msgpack",
        "zstandard",  # 修正包名
        "pyjwt",
        "asgiref",
        "redis"
    ],
    extras_require={
        "fastapi": ["fastapi", "uvicorn"],
        "langchain": ["langchain"],
        "wasm": ["wasmer"],  # 添加Wasm支持
        "opentelemetry": ["opentelemetry-api", "opentelemetry-sdk", "opentelemetry-exporter-otlp"],  # 添加OpenTelemetry支持
        "testing": ["pytest", "pytest-asyncio"]
    },
    entry_points={
        "console_scripts": [
            "w-agent=w_agent.cli:main"
        ]
    }
)