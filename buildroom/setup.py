"""Setup configuration for buildroom package."""

from setuptools import setup, find_packages

setup(
    name="goku-buildroom",
    version="0.1.0",
    description="Shared utilities for Goku agents",
    author="Goku Contributors",
    license="MIT",
    packages=find_packages(include=["agent_lib"]),
    python_requires=">=3.9",
    install_requires=[
        "pyyaml>=6.0",
        "jsonschema>=4.0",
        "httpx>=0.24.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0",
            "black>=23.0",
            "ruff>=0.1.0",
        ],
    },
)
