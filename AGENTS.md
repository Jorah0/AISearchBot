# Project Agents and Configuration

## Overview
This is the Lodestar job search automation tool with a complex codebase that can cause context overflow issues.

## Key Areas
- Core modules in `lodestar/` directory
- Tests in `tests/` directory
- Documentation in `docs/` directory
- Extension in `extension/` directory

## Configuration for Context Management
To avoid context overflow errors:
1. Limit file processing to core modules only when possible
2. Use specific ignore patterns for cache and build directories
3. Implement proper filtering for large files

## File Patterns to Ignore
- Cache directories: `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`
- Build artifacts: `dist`, `build`, `*.egg-info`  
- Virtual environments: `.venv`
- Git directories: `.git`
- Node modules: `node_modules`
- Test artifacts: `test_*`, `reports`, `tmp`, `temp`
- Log files: `*.log`, `coverage.xml`

## Context Limits
- Maximum context lines: 10,000 (to prevent overflow)
- Maximum file size: 10MB (to avoid loading huge files)