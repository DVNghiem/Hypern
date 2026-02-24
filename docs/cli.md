# Hypern CLI

Hypern ships with a built-in command-line interface that helps you **scaffold new projects** and **run your application** without writing boilerplate startup scripts.

## Installation

The CLI is included automatically when you install Hypern:

```bash
pip install hypern
```

Verify the installation:

```bash
hypern --help
```

---

## Commands

### `hypern new`

Scaffold a new Hypern project from a supported architecture pattern.

```bash
hypern new <project-name> [options]
```

**Arguments**

| Argument | Description |
|---|---|
| `name` | The name of the new project (used as the directory name) |

**Options**

| Option | Short | Default | Description |
|---|---|---|---|
| `--pattern` | `-p` | _(interactive)_ | Architecture pattern to use (see below) |
| `--directory` | `-d` | `.` | Parent directory where the project folder will be created |

**Architecture Patterns**

| Pattern | Description |
|---|---|
| `layered` | Classic N-tier / Layered architecture |
| `ddd` | Domain-Driven Design (DDD) + Layered |
| `hexagonal` | Hexagonal (Ports & Adapters) |
| `onion` | Onion Architecture |
| `clean` | Clean Architecture |
| `cqrs` | CQRS (Command-Query Responsibility Segregation) |
| `saga` | SAGA pattern |
| `event-driven` | Event-Driven / Event Sourcing |
| `saga-event` | Combined SAGA + Event-Driven / Event Sourcing |

If `--pattern` is omitted, an interactive prompt lets you choose one.

**Examples**

```bash
# Interactive pattern selection
hypern new myproject

# Specify a pattern directly
hypern new myproject --pattern layered

# Create under a specific parent directory
hypern new myproject --pattern clean --directory /srv/apps
```

**Generated Files**

Every scaffold produces a ready-to-run project containing at minimum:

- `app.py` – application entry point with a sample health endpoint
- `config.py` – environment-aware configuration class
- `requirements.txt` – pinned Hypern dependency
- `.env.example` – example environment variables
- `.gitignore` – sensible Python/IDE ignores
- `README.md` – quick-start instructions
- `tests/` – placeholder test suite

The internal structure varies by architecture pattern (e.g., `ddd` adds `domain/`, `application/`, `infrastructure/` layers).

---

### `hypern run`

Start your Hypern application.

```bash
hypern run [options]
```

**Options**

| Option | Short | Default | Description |
|---|---|---|---|
| `--app` | `-a` | _(auto-discover)_ | Application instance path in `module:attribute` format |
| `--host` | | `127.0.0.1` | Host address to bind |
| `--port` | | `5000` | Port to listen on |
| `--workers` | `-w` | `1` | Number of worker processes |
| `--reload` | | `false` | Enable auto-reload on file changes |
| `--debug` | | `false` | Enable debug mode |

**App Auto-Discovery**

When `--app` is not provided, Hypern scans the current working directory for a `Hypern` instance using these common patterns (in order):

| Module | Attribute |
|---|---|
| `app` | `app` |
| `app` | `application` |
| `main` | `app` |
| `main` | `application` |
| `server` | `app` |
| `server` | `application` |
| `application` | `app` |
| `application` | `application` |

If none of the above match, every `.py` file in the current directory is inspected for a `Hypern` instance.

**Examples**

```bash
# Auto-discover the app and run on defaults (127.0.0.1:5000)
hypern run

# Specify the app explicitly
hypern run --app myapp.app:app

# Custom host / port
hypern run --host 0.0.0.0 --port 8080

# Production: multiple workers
hypern run --host 0.0.0.0 --port 8080 --workers 4

# Development: hot-reload + debug
hypern run --reload --debug
```

---

## Typical Workflow

```bash
# 1. Scaffold a new project
hypern new myapi --pattern layered

# 2. Enter the project directory
cd myapi

# 3. Install dependencies
pip install -r requirements.txt

# 4. Start the development server
hypern run --reload --debug
```

---

## Environment Variables

You can override CLI defaults via environment variables in your `.env` file:

```bash
HOST=0.0.0.0
PORT=8080
WORKERS=4
APP_ENV=production
DEBUG=false
```

!!! tip
    Use a tool like [`python-dotenv`](https://pypi.org/project/python-dotenv/) or configure your deployment platform to inject these variables automatically.
