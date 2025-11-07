"""Setup script for detectkit."""

from pathlib import Path
from setuptools import find_packages, setup

# Read requirements
with open("requirements.txt") as f:
    requirements = [line.strip() for line in f if line.strip() and not line.startswith("#")]

setup(
    name="detectkit",
    version="0.1.0",
    description="Anomaly Detection for Time-Series Metrics",
    long_description=open("README.md").read() if Path("README.md").exists() else "",
    long_description_content_type="text/markdown",
    author="detectkit team",
    url="https://github.com/alexeiveselov92/detectkit",
    python_requires=">=3.10",
    packages=find_packages(exclude=["tests*"]),
    install_requires=requirements,
    extras_require={
        "clickhouse": ["clickhouse-driver>=0.2.0"],
        "postgres": ["psycopg2-binary>=2.9.0"],
        "mysql": ["pymysql>=1.0.0"],
        "advanced": ["prophet>=1.1.0"],
        "dev": [
            "pytest>=7.0.0",
            "pytest-cov>=4.0.0",
            "black>=22.0.0",
            "mypy>=1.0.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "dtk=detectkit.cli.main:cli",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
)
