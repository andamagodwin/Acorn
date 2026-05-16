"""Allows `pip install -e .` for development and `acorn` command."""
from setuptools import setup, find_packages

setup(
    name="acorn-agent",
    version="2.1.0",
    description="An autonomous coding agent that lives in your terminal",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="Andama Godwin",
    url="https://github.com/andamagodwin/Acorn",
    license="MIT",
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
    classifiers=[
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: OS Independent",
        "Topic :: Software Development :: Code Generators",
        "Intended Audience :: Developers",
    ],
)
