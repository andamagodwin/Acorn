"""Allows `pip install -e .` for development and `nova` command."""
from setuptools import setup, find_packages

setup(
    name="nova-agent",
    version="2.0.0",
    packages=find_packages(),
    install_requires=[
        "google-genai>=1.0.0",
        "google-cloud-aiplatform>=1.60.0",
    ],
    entry_points={
        "console_scripts": [
            "nova=nova.main:main",
        ],
    },
    python_requires=">=3.11",
)
