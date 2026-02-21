"""Shared template helpers used by all architecture pattern generators."""

from __future__ import annotations

from typing import Dict


def readme(name: str, pattern_label: str) -> str:
    """Generate README.md content."""
    return f"""\
# {name}

A [Hypern](https://github.com/DVNghiem/Hypern) project using **{pattern_label}** architecture.

## Getting Started

```bash
# Install dependencies
pip install -r requirements.txt

# Run the application
hypern run
```

## Project Structure

This project was scaffolded with `hypern new {name} --pattern <pattern>`.
Refer to the Hypern documentation for more details.
"""


def requirements() -> str:
    """Generate requirements.txt content."""
    return """\
hypern>=1.0.0
"""


def config(name: str) -> str:
    """Generate config.py content."""
    return f'''\
"""Application configuration for {name}."""

import os


class Config:
    """Base configuration."""

    APP_NAME: str = "{name}"
    DEBUG: bool = os.getenv("DEBUG", "false").lower() in ("1", "true", "yes")
    HOST: str = os.getenv("HOST", "127.0.0.1")
    PORT: int = int(os.getenv("PORT", "5000"))
    WORKERS: int = int(os.getenv("WORKERS", "1"))


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False
    WORKERS = 4


def get_config() -> Config:
    env = os.getenv("APP_ENV", "development").lower()
    configs = {{
        "development": DevelopmentConfig,
        "production": ProductionConfig,
    }}
    return configs.get(env, DevelopmentConfig)()
'''


def test_health() -> str:
    """Generate a basic health-check test."""
    return '''\
"""Basic health check test."""


def test_health_endpoint():
    """Placeholder test – replace with real HTTP test."""
    assert True
'''


def health_controller() -> str:
    """Generate a standard health endpoint controller."""
    return '''\
"""Health endpoint."""

from hypern import Router, Request, Response

health_router = Router(prefix="")


@health_router.get("/health")
async def health(request: Request) -> Response:
    return Response(status_code=200, description={"status": "ok"})
'''


def gitignore() -> str:
    """Generate .gitignore content."""
    return """\
__pycache__/
*.py[cod]
*$py.class
*.egg-info/
dist/
build/
.eggs/
*.egg
.env
.venv/
venv/
env/
*.db
*.sqlite3
.idea/
.vscode/
*.swp
*.swo
.DS_Store
"""


def env_example() -> str:
    """Generate .env.example content."""
    return """\
# Application
APP_ENV=development
DEBUG=true
HOST=127.0.0.1
PORT=5000
WORKERS=1

# Database (if applicable)
# DATABASE_URL=postgresql://user:pass@localhost:5432/dbname
"""


def base_files(name: str, pattern_label: str) -> Dict[str, str]:
    """Return the files common to every scaffolded project."""
    return {
        "config.py": config(name),
        "requirements.txt": requirements(),
        "README.md": readme(name, pattern_label),
        ".gitignore": gitignore(),
        ".env.example": env_example(),
        "tests/__init__.py": "",
        "tests/test_health.py": test_health(),
    }
