# Contributing to pystata-x

Thank you for your interest in contributing to pystata-x! This guide will help you set up your development environment, run tests, and understand the project structure.

## Table of Contents

- [Development Setup](#development-setup)
- [Building the Project](#building-the-project)
- [Testing](#testing)
- [Submitting Changes](#submitting-changes)

## Development Setup

### Prerequisites

- **Stata 17+** (Required for integration tests)
- **Python 3.11+**
- **uv** (Recommended) or pip

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/tmonk/pystata-x.git
   cd pystata-x
   ```

2. Install dependencies with uv:
   ```bash
   uv sync --dev
   ```

   Or with pip:
   ```bash
   pip install -e .[dev]
   ```

## Building the Project

The project uses **hatchling** as the Python build backend. To build wheels:

```bash
uv build
```

Or using the build module directly:

```bash
python -m build
```

## Testing

The test suite is organised with pytest markers.

### All Tests (Requires Stata)

```bash
uv run pytest
```

### Tests Without Stata (Fast/CI)

```bash
uv run pytest -v -m "not requires_stata"
```

### Test Coverage

Generate a coverage report:

```bash
uv run pytest --cov=pystata_x --cov-report=term-missing
```

Or generate an HTML report:

```bash
uv run pytest --cov=pystata_x --cov-report=html
open htmlcov/index.html  # View the report
```

### Writing Tests

When adding new tests:

1. **Mark Stata-dependent tests**:
   ```python
   import pytest

   # At module level for all tests
   pytestmark = pytest.mark.requires_stata

   # Or for individual tests
   @pytest.mark.requires_stata
   def test_my_stata_feature():
       pass
   ```

2. **Mark slow tests**:
   ```python
   @pytest.mark.slow
   def test_expensive_operation():
       pass
   ```

## Submitting Changes

### Pull Request Process

1. **Create a feature branch**:
   ```bash
   git checkout -b feature/my-feature
   ```

2. **Develop and Test**:
   - Add tests in `tests/`.
   - Ensure `pytest -v -m "not requires_stata"` passes.

3. **Commit with clear messages**:
   Follow conventional commits (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `perf:`, `test:`).

4. **Push and create a pull request**:
   ```bash
   git push origin feature/my-feature
   ```

### CI/CD

GitHub Actions automatically runs on all PRs:
- Runs all non-Stata tests (`pytest -v -m "not requires_stata"`)
- Tests on Ubuntu with Python 3.11–3.14
- Builds the package and tests entry points

## Project Structure

- `src/pystata_x/`: Python source code.
- `tests/`: Test suite.
- `scripts/`: Utilities for benchmarks and version syncing.

## Getting Help

- **Issues**: [GitHub Issues](https://github.com/tmonk/pystata-x/issues)
- **Author**: [Thomas Monk](https://tdmonk.com)

## License

By contributing to pystata-x, you agree that your contributions will be licensed under the GNU Affero General Public License v3.0.
