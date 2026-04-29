# AI Changelog Generator

GitHub Action that generates structured changelogs on release using LLMs.

## Stack

- Python 3.11+, only runtime dependency: `requests>=2.32`
- Package manager: uv
- Lint/format: ruff (line-length=100, py311)
- Type check: mypy --strict
- Test: pytest + pytest-cov (target >=90%)

## Commands

```bash
uv sync --dev                                          # Install deps
uv run pytest tests/ -v --cov=changelog               # Run tests
uv run ruff check changelog/ tests/ generate.py       # Lint
uv run ruff format changelog/ tests/ generate.py      # Format
uv run mypy changelog/ generate.py                    # Type check
```

## Architecture

```
generate.py          # Entry point (CLI)
changelog/           # Main package
  config.py          # Config.from_env() — single source of truth for env vars
  exceptions.py      # ChangelogError hierarchy
  github_client.py   # GitHub REST API client with retry/backoff
  classifier.py      # Heuristic commit/PR classifier
  prompt.py          # LLM prompt builders
  providers.py       # Multi-provider LLM with fallback + rate limit handling
  evaluator.py       # Self-evaluation loop (fail-safe)
  publisher.py       # Publish to GitHub release + optional CHANGELOG.md
```

## Key Constraints

- Zero `print()` — use `logging` exclusively
- Zero `os.environ` outside `Config.from_env()`
- Self-evaluation never blocks publishing
- `[skip ci]` on all automated commits
- Tokens/API keys never in logs
