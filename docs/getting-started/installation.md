# Installation

This guide will walk you through installing Hypern and setting up your development environment.

## Requirements

Before installing Hypern, ensure you have the following prerequisites:

- **Python**: 3.11 or higher (< 4.0)
- **pip**: Latest version recommended
- **Operating System**: Linux, macOS, or Windows

## Quick Installation

The simplest way to install Hypern is using pip:

```bash
pip install hypern
```

This will install Hypern and its core dependencies:
- `orjson` - Fast JSON serialization
- `msgpack` - Efficient binary serialization
- `uvloop` - High-performance event loop (on supported platforms)

## Development Installation

If you want to contribute to Hypern or modify the source code, follow these steps:

### 1. Clone the Repository

```bash
git clone https://github.com/martindang/hypern.git
cd hypern
```

### 2. Set Up Virtual Environment

Create and activate a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate  # On Linux/macOS
# or
.\venv\Scripts\activate  # On Windows
```

### 3. Install Development Tools

Install the required build tools:

```bash
pip install pre-commit poetry maturin
```

**Tool Overview:**
- `pre-commit`: Git hooks for code quality
- `poetry`: Dependency management
- `maturin`: Build Rust extensions for Python

### 4. Install Dependencies

Install all development and test dependencies:

```bash
poetry install --with dev --with test
```

### 5. Install Pre-commit Hooks

Set up pre-commit hooks to maintain code quality:

```bash
pre-commit install
```

### 6. Build Rust Extension

Build and install the Rust components:

```bash
maturin develop
```

For production builds with optimizations:

```bash
maturin develop --release
```

## Platform-Specific Notes

### Linux

On Linux systems, Hypern uses `jemalloc` for memory allocation by default, which provides better performance. No additional setup is required.

### macOS

macOS is fully supported. If you're on Apple Silicon (M1/M2), ensure you're using a compatible Python version.

### Windows

On Windows, some features like `uvloop` are not available. Hypern will automatically fall back to the standard asyncio event loop.

### ARM (armv7l)

For ARM platforms like Raspberry Pi, `uvloop` may not be available. The framework will work but with slightly reduced performance.

## Verify Installation

After installation, verify that Hypern is properly installed:

```bash
python -c "import hypern; print(hypern.__version__)"
```

Or create a simple test file:

```python
# test_hypern.py
from hypern import Hypern

app = Hypern()

if __name__ == "__main__":
    print("Hypern is installed correctly!")
    print(f"Version: {hypern.__version__}")
```

Run it:

```bash
python test_hypern.py
```

## Troubleshooting

### Rust Compiler Not Found

If you encounter errors about Rust not being found during development installation:

1. Install Rust from [rustup.rs](https://rustup.rs/):
   ```bash
   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
   ```

2. Restart your terminal or source the Rust environment:
   ```bash
   source $HOME/.cargo/env
   ```

### Build Errors on Windows

If you encounter build errors on Windows:

1. Install Microsoft C++ Build Tools from [Visual Studio](https://visualstudio.microsoft.com/downloads/)
2. Ensure you select "Desktop development with C++" during installation

### Python Version Issues

If you have multiple Python versions installed:

```bash
# Use specific Python version
python3.11 -m pip install hypern

# Or with virtual environment
python3.11 -m venv venv
source venv/bin/activate
pip install hypern
```

### Import Errors

If you get import errors after installation:

1. Ensure you're in the correct virtual environment
2. Verify the installation: `pip list | grep hypern`
3. Reinstall if necessary: `pip install --force-reinstall hypern`

## Updating Hypern

To update to the latest version:

```bash
pip install --upgrade hypern
```

For development installations:

```bash
git pull origin main
poetry install --with dev --with test
maturin develop --release
```

## Next Steps

Now that you have Hypern installed, proceed to:

- [Quick Start Guide](quickstart.md) - Build your first application
- [Basic Concepts](concepts.md) - Learn core concepts
- [Project Structure](project-structure.md) - Organize your project

## Additional Resources

- [GitHub Repository](https://github.com/martindang/hypern)
- [PyPI Package](https://pypi.org/project/hypern/)
- [Issue Tracker](https://github.com/martindang/hypern/issues)