# Lodestar Configuration for Kilo

This file provides configuration settings to help prevent context overflow issues when working with the large Lodestar codebase.

## Ignore Patterns
The following directories and files are ignored to reduce context size:
- Cache directories: __pycache__, .pytest_cache, .mypy_cache, .ruff_cache
- Build artifacts: dist, build, *.egg-info  
- Virtual environments: .venv
- Git directories: .git
- Node modules: node_modules
- Test artifacts: test_*, reports, tmp, temp
- Log files: *.log, coverage.xml

## Context Management
To prevent the ContextOverflowError:
1. Limit file processing to core modules only when possible
2. Use specific ignore patterns for large directories
3. Implement proper filtering for large files