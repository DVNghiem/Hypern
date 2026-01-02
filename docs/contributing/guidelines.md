# Contributing Guidelines

Thank you for your interest in contributing to Hypern! This document provides guidelines and instructions for contributing to the project.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [How to Contribute](#how-to-contribute)
- [Coding Standards](#coding-standards)
- [Testing](#testing)
- [Documentation](#documentation)
- [Pull Request Process](#pull-request-process)
- [Community](#community)

## Code of Conduct

By participating in this project, you agree to abide by our [Code of Conduct](code-of-conduct.md). Please read it before contributing.

## Getting Started

### Prerequisites

Before contributing, ensure you have:

- Python 3.11 or higher
- Rust toolchain (rustc, cargo)
- Git
- Basic knowledge of Python and/or Rust

### Finding Issues to Work On

1. Check the [issue tracker](https://github.com/DVNghiem/hypern/issues)
2. Look for issues labeled `good first issue` or `help wanted`
3. Comment on the issue to express interest
4. Wait for maintainer approval before starting work

## Development Setup

### 1. Fork and Clone

```bash
# Fork the repository on GitHub
# Then clone your fork
git clone https://github.com/YOUR_USERNAME/hypern.git
cd hypern
```

### 2. Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: .\venv\Scripts\activate
```

### 3. Install Development Dependencies

```bash
pip install pre-commit poetry maturin
poetry install --with dev --with test
```

### 4. Install Pre-commit Hooks

```bash
pre-commit install
```

### 5. Build Rust Extension

```bash
maturin develop
```

### 6. Run Tests

```bash
pytest
```

## How to Contribute

### Reporting Bugs

When reporting bugs, please include:

- **Clear title**: Describe the issue briefly
- **Description**: Detailed explanation of the bug
- **Steps to reproduce**: Step-by-step instructions
- **Expected behavior**: What should happen
- **Actual behavior**: What actually happens
- **Environment**: OS, Python version, Hypern version
- **Code samples**: Minimal reproducible example

**Example:**

```markdown
## Bug: Response not sent when finish() is not called

**Environment:**
- OS: Ubuntu 22.04
- Python: 3.11.5
- Hypern: 0.3.15

**Steps to reproduce:**
1. Create handler without response.finish()
2. Make request to endpoint
3. Client hangs waiting for response

**Expected:** Error or warning should be raised
**Actual:** Request hangs indefinitely

**Code:**
```python
@app.get("/test")
def handler(request, response):
    response.status(200)
    response.body_str("test")
    # Missing response.finish()
```
```

### Suggesting Features

Feature requests should include:

- **Use case**: Why is this feature needed?
- **Proposed solution**: How should it work?
- **Alternatives**: Other approaches considered
- **Examples**: Code examples of proposed API

### Contributing Code

1. **Create a branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes**
   - Write clean, readable code
   - Follow coding standards
   - Add tests for new features
   - Update documentation

3. **Test your changes**
   ```bash
   pytest
   ```

4. **Commit your changes**
   ```bash
   git add .
   git commit -m "feat: add awesome feature"
   ```

5. **Push to your fork**
   ```bash
   git push origin feature/your-feature-name
   ```

6. **Create a Pull Request**
   - Go to GitHub and create a PR
   - Fill out the PR template
   - Link related issues

## Coding Standards

### Python Code

#### Style Guide

- Follow [PEP 8](https://pep8.org/)
- Use type hints for all functions
- Maximum line length: 160 characters
- Use descriptive variable names

#### Example

```python
from typing import List, Optional
from hypern import Request, Response

def get_user_by_id(user_id: int) -> Optional[dict]:
    """
    Retrieve a user by their ID.
    
    Args:
        user_id: The unique identifier for the user
    
    Returns:
        User dictionary if found, None otherwise
    """
    # Implementation here
    pass
```

#### Tools

We use the following tools (configured in pre-commit):

- **ruff**: Fast Python linter
- **black**: Code formatter
- **isort**: Import sorter
- **mypy**: Static type checker

Run manually:

```bash
# Format code
black .

# Sort imports
isort .

# Lint
ruff check .

# Type check
mypy hypern/
```

### Rust Code

#### Style Guide

- Follow Rust standard style (`rustfmt`)
- Use meaningful variable names
- Add comments for complex logic
- Write idiomatic Rust

#### Example

```rust
/// Represents an HTTP request
pub struct Request {
    pub path: String,
    pub method: String,
}

impl Request {
    /// Creates a new Request instance
    pub fn new(path: String, method: String) -> Self {
        Self { path, method }
    }
}
```

#### Tools

```bash
# Format Rust code
cargo fmt

# Lint Rust code
cargo clippy

# Run Rust tests
cargo test
```

### Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation changes
- `style:` - Code style changes (formatting)
- `refactor:` - Code refactoring
- `test:` - Adding or updating tests
- `chore:` - Maintenance tasks

**Examples:**

```
feat: add WebSocket support for real-time communication

fix: resolve memory leak in request handler

docs: update installation guide with Windows instructions

refactor: simplify routing logic for better performance
```

## Testing

### Writing Tests

#### Python Tests

```python
import pytest
from hypern import Hypern

def test_route_registration():
    app = Hypern()
    
    @app.get("/test")
    def handler(request, response):
        response.status(200)
        response.body_str("test")
        response.finish()
    
    # Test assertions
    assert app is not None
```

#### Integration Tests

```python
import requests
from multiprocessing import Process
import time

def test_endpoint():
    # Start server
    p = Process(target=run_server)
    p.start()
    time.sleep(1)
    
    # Test
    response = requests.get("http://localhost:5001/test")
    assert response.status_code == 200
    
    # Cleanup
    p.terminate()
    p.join()
```

### Running Tests

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_basic_api.py

# Run with coverage
pytest --cov=hypern

# Run with verbose output
pytest -v
```

### Test Coverage

- Aim for >80% code coverage
- All new features must include tests
- Bug fixes should include regression tests

## Documentation

### Types of Documentation

1. **Code Comments**: Explain complex logic
2. **Docstrings**: Document all public APIs
3. **User Guide**: Tutorials and how-tos
4. **API Reference**: Complete API documentation

### Writing Documentation

#### Docstrings

Use Google-style docstrings:

```python
def process_request(request: Request, config: dict) -> Response:
    """
    Process an incoming HTTP request.
    
    Args:
        request: The incoming HTTP request object
        config: Configuration dictionary for processing
    
    Returns:
        Processed HTTP response object
    
    Raises:
        ValueError: If request is invalid
        RuntimeError: If processing fails
    
    Example:
        >>> request = Request(path="/api/users", method="GET")
        >>> config = {"timeout": 30}
        >>> response = process_request(request, config)
    """
    pass
```

#### User Documentation

Documentation is written in Markdown and built with MkDocs:

```bash
# Install MkDocs
pip install mkdocs mkdocs-material mkdocstrings

# Serve documentation locally
mkdocs serve

# Build documentation
mkdocs build
```

Add documentation files to `docs/` directory following the existing structure.

## Pull Request Process

### Before Submitting

- [ ] Code follows style guidelines
- [ ] Tests pass locally
- [ ] New tests added for new features
- [ ] Documentation updated
- [ ] Commit messages follow conventions
- [ ] Branch is up to date with main

### PR Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Related Issues
Fixes #123

## Testing
Describe testing performed

## Checklist
- [ ] Tests pass
- [ ] Documentation updated
- [ ] Code reviewed
```

### Review Process

1. **Automated checks**: CI runs tests and lints
2. **Code review**: Maintainer reviews code
3. **Feedback**: Address review comments
4. **Approval**: Maintainer approves PR
5. **Merge**: PR is merged to main

### After Merge

- Your contribution will be included in the next release
- You'll be added to the contributors list
- Close any related issues

## Community

### Communication Channels

- **GitHub Issues**: Bug reports and feature requests
- **GitHub Discussions**: General questions and discussions
- **Pull Requests**: Code contributions

### Getting Help

If you need help:

1. Check existing documentation
2. Search closed issues
3. Ask in GitHub Discussions
4. Contact maintainers

## Recognition

Contributors are recognized in:

- README.md contributors section
- Release notes
- Documentation credits

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

## Questions?

If you have questions about contributing, please:

1. Read this guide thoroughly
2. Check existing issues and discussions
3. Create a new discussion if needed

Thank you for contributing to Hypern! 🚀
