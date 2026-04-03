# Operations Guide

This guide provides detailed information for Git operations and release management in IntentKit.

## Git Commit

### Pre-commit Steps

1. Run `ruff format && ruff check --fix` before commit.
2. Make sure all tests pass before commit.

### Commit Message Format

When you generate git commit message, always start with one of `feat/fix/chore/docs/test/refactor/improve`. 

**Format**: `<type>: <subject>`

- Subject should start with lowercase
- Only one-line needed, do not generate commit message body

**Examples**:
- `feat: add new twitter skill`
- `fix: resolve circular dependency in models`
- `chore: update dependencies`

## Github Release

### Version Number Rules

Follow Semantic Versioning

### Release Steps

1. Make sure `main` is up to date and the working tree is clean.
2. Bump the package version in `pyproject.toml` and `intentkit/__init__.py`.
3. Update any release notes or changelog entries you want committed with that version.
4. Commit and push the release commit to `main`.
5. Create an annotated `vX.Y.Z` tag on that commit and push the tag.
6. GitHub Actions `release.yml` will build the package, publish it through PyPI Trusted Publishing, and create the GitHub release automatically.
