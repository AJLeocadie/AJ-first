"""Setup pour URSSAF Analyzer."""

from setuptools import setup, find_packages

setup(
    name="urssaf_analyzer",
    version="1.0.0",
    description="Logiciel securise d'analyse de documents sociaux et fiscaux URSSAF",
    author="AJ",
    python_requires=">=3.10",
    packages=find_packages(),
    entry_points={
        "console_scripts": [
            "urssaf-analyzer=urssaf_analyzer.main:main",
        ],
    },
    install_requires=[
        "pydantic>=2.0",
        "pdfplumber>=0.10.0",
        "openpyxl>=3.1.0",
        "lxml>=4.9.0",
        "cryptography>=41.0.0",
        "jinja2>=3.1.0",
        "click>=8.1.0",
        "python-dateutil>=2.8.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.4.0",
            "pytest-cov>=4.1.0",
        ],
    },
)
