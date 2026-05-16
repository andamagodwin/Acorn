"""Allows `pip install -e .` for development and `acorn` command."""
from setuptools import setup, find_packages

setup(
    name="acorn-agent",
    version="2.0.0",
    packages=find_packages(),
    install_requires=[
        "google-genai>=1.0.0",
        "google-cloud-aiplatform>=1.60.0",
    ],
    entry_points={
        "console_scripts": [
            "acorn=acorn.main:main",
        ],
    },
    python_requires=">=3.11",
)
