# ai-changelog-generator — Project Specification

> Document version: 1.0  
> Author: AndreaBonn  
> Status: Ready for implementation  
> Reference project: [ai-pr-reviewer](https://github.com/AndreaBonn/ai-pr-reviewer)

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Goals and Non-Goals](#2-goals-and-non-goals)
3. [Architecture Overview](#3-architecture-overview)
4. [Repository Structure](#4-repository-structure)
5. [GitHub Action — `action.yml`](#5-github-action--actionyml)
6. [Entry Point — `generate.py`](#6-entry-point--generatepy)
7. [Package Structure — `changelog/`](#7-package-structure--changelog)
   - 7.1 [config.py](#71-configpy)
   - 7.2 [exceptions.py](#72-exceptionspy)
   - 7.3 [github_client.py](#73-github_clientpy)
   - 7.4 [classifier.py](#74-classifierpy)
   - 7.5 [prompt.py](#75-promptpy)
   - 7.6 [providers.py](#76-providerspy)
   - 7.7 [evaluator.py](#77-evaluatorpy)
   - 7.8 [publisher.py](#78-publisherpy)
8. [Pipeline Logic](#8-pipeline-logic)
9. [Prompt Engineering](#9-prompt-engineering)
   - 9.1 [Generation prompt](#91-generation-prompt)
   - 9.2 [Self-evaluation prompt](#92-self-evaluation-prompt)
10. [LLM Provider System](#10-llm-provider-system)
11. [GitHub API Usage](#11-github-api-usage)
12. [Output Format](#12-output-format)
13. [Inputs Reference](#13-inputs-reference)
14. [Environment Variables](#14-environment-variables)
15. [Error Handling and Exit Codes](#15-error-handling-and-exit-codes)
16. [Test Suite](#16-test-suite)
17. [CI/CD Pipeline](#17-cicd-pipeline)
18. [Packaging and Tooling](#18-packaging-and-tooling)
19. [Security Policy](#19-security-policy)
20. [README Requirements](#20-readme-requirements)
21. [Behavioural Constraints for Implementation](#21-behavioural-constraints-for-implementation)

---

## 1. Project Overview

`ai-changelog-generator` is a GitHub Action that automatically generates a structured, human-readable changelog whenever a new release or tag is published. It analyses the commits and merged pull requests between the previous tag and the current one, classifies them by type, generates a changelog using an LLM, and self-evaluates the output before publishing it.

The tool targets **any developer or team that uses GitHub releases** and finds writing changelogs tedious or inconsistent. It requires zero configuration beyond an API key for a free LLM provider (Groq or Gemini).

It is the **sibling project** of [ai-pr-reviewer](https://github.com/AndreaBonn/ai-pr-reviewer) and shares the same design principles:

- Zero heavy dependencies (only `requests` in production)
- Multi-provider with automatic fallback and key rotation
- Free-tier providers (Groq, Gemini) as default
- Production-grade code: tests, CI, badges, security policy, bilingual README

---

## 2. Goals and Non-Goals

### Goals

- Generate a structured changelog automatically on `release` or `push: tags` events
- Support multi-provider LLM with fallback chain (Groq → Gemini → Anthropic → OpenAI)
- Classify commits and PRs into semantic categories (breaking change, feature, fix, chore, docs, perf, refactor)
- Perform self-evaluation of the generated changelog to detect missing breaking changes or major features before publishing
- Publish the changelog as the GitHub Release body
- Optionally prepend the changelog to `CHANGELOG.md` in the repository via a commit
- Support multiple output languages (English, Italian, French, Spanish, German)
- Require only `requests` as a runtime dependency

### Non-Goals

- Does not parse or enforce Conventional Commits format (it works with any commit message style, using LLM classification)
- Does not generate release notes for non-GitHub platforms
- Does not run tests or validate code
- Does not support GitHub Enterprise Server (only github.com)
- Does not require a vector database or embedding model

---

## 3. Architecture Overview

```
GitHub Event (release published / tag push)
        │
        ▼
  action.yml  ←─── user workflow YAML
        │
        ▼
  generate.py  (entry point)
        │
        ├── Config.from_env()
        ├── GitHubClient  ──► GitHub REST API
        │       ├── get_tags()
        │       ├── get_commits_between()
        │       ├── get_merged_prs()
        │       └── get_pr_labels()
        │
        ├── Classifier
        │       └── classify_commits()  ──► LLM call (optional) or heuristic
        │
        ├── PromptBuilder
        │       └── build_generation_prompt()
        │
        ├── LLMProviderChain
        │       └── call_llm_with_fallback()  ──► Groq / Gemini / Anthropic / OpenAI
        │
        ├── Evaluator
        │       ├── build_evaluation_prompt()
        │       ├── call_llm_with_fallback()
        │       └── evaluate()  ──► returns (ok: bool, feedback: str)
        │
        └── Publisher
                ├── update_release_body()  ──► GitHub Releases API
                └── update_changelog_file()  ──► GitHub Contents API (optional)
```

---

## 4. Repository Structure

```
ai-changelog-generator/
│
├── action.yml                        # GitHub Action definition
├── generate.py                       # Entry point
├── pyproject.toml                    # Project metadata and tool config
├── requirements.txt                  # Runtime deps (requests only)
├── uv.lock                           # Lockfile
├── install.sh                        # Not needed for this project (Action only)
│
├── changelog/                        # Main package
│   ├── __init__.py
│   ├── config.py
│   ├── exceptions.py
│   ├── github_client.py
│   ├── classifier.py
│   ├── prompt.py
│   ├── providers.py
│   ├── evaluator.py
│   └── publisher.py
│
├── tests/
│   ├── __init__.py
│   ├── test_config.py
│   ├── test_classifier.py
│   ├── test_prompt.py
│   ├── test_providers.py
│   ├── test_evaluator.py
│   ├── test_publisher.py
│   ├── test_github_client.py
│   └── test_generate.py
│
├── .github/
│   └── workflows/
│       ├── test.yml                  # CI: tests + lint on PR and push
│       └── release.yml               # Tags a new version on manual trigger
│
├── assets/
│   └── changelog-example.png         # Screenshot for README
│
├── badges/
│   ├── test-badge.json
│   └── coverage-badge.json
│
├── README.md
├── README.it.md
├── SECURITY.md
├── SECURITY.it.md
├── LICENSE                           # Apache 2.0
└── NOTICE
```

---

## 5. GitHub Action — `action.yml`

```yaml
name: 'AI Changelog Generator by Bonn'
description: 'Automatically generates a structured changelog on release using an LLM (Groq, Gemini, Anthropic or OpenAI)'
author: 'AndreaBonn'

inputs:
  llm_provider:
    description: 'LLM provider(s), comma-separated for fallback: "groq", "groq,gemini", "groq,groq,gemini"'
    required: false
    default: 'groq'

  llm_api_key:
    description: 'API key(s), comma-separated, one per provider entry'
    required: true

  llm_model:
    description: 'Override the default model for the first provider (optional)'
    required: false
    default: ''

  github_token:
    description: 'GitHub token for reading repo data and publishing the changelog'
    required: true

  language:
    description: 'Output language: "english", "italian", "french", "spanish", "german"'
    required: false
    default: 'english'

  update_changelog_file:
    description: 'If "true", prepend the changelog to CHANGELOG.md and commit it'
    required: false
    default: 'false'

  changelog_file_path:
    description: 'Path to the CHANGELOG.md file (used only if update_changelog_file is true)'
    required: false
    default: 'CHANGELOG.md'

  max_commits:
    description: 'Maximum number of commits to include in the LLM context'
    required: false
    default: '100'

  max_prs:
    description: 'Maximum number of merged PRs to include in the LLM context'
    required: false
    default: '30'

  max_eval_retries:
    description: 'Maximum self-evaluation retries if the changelog fails quality check (0 to disable)'
    required: false
    default: '1'

runs:
  using: 'composite'
  steps:
    - name: Set up Python
      uses: actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405 # v6.2.0
      with:
        python-version: '3.11'
        cache: 'pip'

    - name: Install dependencies
      shell: bash
      run: pip install -r ${{ github.action_path }}/requirements.txt

    - name: Generate Changelog
      shell: bash
      env:
        LLM_PROVIDER: ${{ inputs.llm_provider }}
        LLM_API_KEY: ${{ inputs.llm_api_key }}
        LLM_MODEL: ${{ inputs.llm_model }}
        GITHUB_TOKEN: ${{ inputs.github_token }}
        CHANGELOG_LANGUAGE: ${{ inputs.language }}
        UPDATE_CHANGELOG_FILE: ${{ inputs.update_changelog_file }}
        CHANGELOG_FILE_PATH: ${{ inputs.changelog_file_path }}
        MAX_COMMITS: ${{ inputs.max_commits }}
        MAX_PRS: ${{ inputs.max_prs }}
        MAX_EVAL_RETRIES: ${{ inputs.max_eval_retries }}
        REPO_FULL_NAME: ${{ github.repository }}
        RELEASE_TAG: ${{ github.event.release.tag_name || github.ref_name }}
        RELEASE_NAME: ${{ github.event.release.name || github.ref_name }}
        RELEASE_ID: ${{ github.event.release.id || '' }}
        DEFAULT_BRANCH: ${{ github.event.repository.default_branch }}
      run: python ${{ github.action_path }}/generate.py

branding:
  icon: 'file-text'
  color: 'green'
```

---

## 6. Entry Point — `generate.py`

```python
"""Entry point for the AI Changelog Generator GitHub Action."""

from __future__ import annotations

import logging
import sys

from changelog.config import Config
from changelog.exceptions import ChangelogError
from changelog.github_client import GitHubClient
from changelog.classifier import Classifier
from changelog.prompt import build_generation_prompt, get_system_prompt
from changelog.providers import call_llm_with_fallback, get_provider
from changelog.evaluator import Evaluator
from changelog.publisher import Publisher

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s | %(message)s",
)
log = logging.getLogger("ai-changelog-generator")


def main() -> None:
    cfg = Config.from_env()
    github = GitHubClient(token=cfg.github_token, repo=cfg.repo)

    log.info(
        "Generating changelog for %s on %s (providers=%s, language=%s)",
        cfg.release_tag,
        cfg.repo,
        ",".join(cfg.llm_providers),
        cfg.language,
    )

    # 1. Determine tag range
    previous_tag = github.get_previous_tag(cfg.release_tag)
    log.info("Comparing %s...%s", previous_tag or "<initial>", cfg.release_tag)

    # 2. Fetch context
    commits = github.get_commits_between(previous_tag, cfg.release_tag, max_commits=cfg.max_commits)
    prs = github.get_merged_prs(previous_tag, cfg.release_tag, max_prs=cfg.max_prs)
    log.info("Fetched %d commits and %d merged PRs.", len(commits), len(prs))

    if not commits and not prs:
        log.info("No commits or PRs found — skipping changelog generation.")
        return

    # 3. Classify
    classifier = Classifier()
    classified = classifier.classify(commits, prs)
    log.info(
        "Classified: %d breaking, %d features, %d fixes, %d other.",
        len(classified.breaking),
        len(classified.features),
        len(classified.fixes),
        len(classified.other),
    )

    # 4. Build provider chain
    provider_chain = []
    for i, (name, key) in enumerate(zip(cfg.llm_providers, cfg.llm_api_keys)):
        model = cfg.llm_model if i == 0 else ""
        provider = get_provider(name=name, api_key=key, model=model)
        system_prompt = get_system_prompt()
        provider_chain.append((provider, system_prompt))

    # 5. Generate changelog
    generation_prompt = build_generation_prompt(
        classified=classified,
        release_tag=cfg.release_tag,
        release_name=cfg.release_name,
        previous_tag=previous_tag,
        language=cfg.language,
        repo=cfg.repo,
    )
    changelog_body = call_llm_with_fallback(provider_chain, user=generation_prompt)
    log.info("Changelog generated (%d chars).", len(changelog_body))

    # 6. Self-evaluation loop
    if cfg.max_eval_retries > 0:
        evaluator = Evaluator(provider_chain=provider_chain)
        changelog_body = evaluator.evaluate_and_refine(
            changelog_body=changelog_body,
            classified=classified,
            language=cfg.language,
            max_retries=cfg.max_eval_retries,
        )

    # 7. Publish
    publisher = Publisher(github=github, cfg=cfg)
    publisher.publish(
        changelog_body=changelog_body,
        release_tag=cfg.release_tag,
    )
    log.info("Changelog published successfully.")


def entrypoint() -> None:
    try:
        main()
    except ChangelogError as exc:
        log.error("[%s] %s", exc.code, exc.message)
        sys.exit(1)
    except Exception as exc:
        log.critical(
            "Unexpected error — please report at https://github.com/AndreaBonn/ai-changelog-generator/issues. "
            "Details: %s: %s",
            type(exc).__name__,
            exc,
        )
        sys.exit(2)


if __name__ == "__main__":
    entrypoint()
```

---

## 7. Package Structure — `changelog/`

### 7.1 `config.py`

Reads all configuration from environment variables (injected by `action.yml`). Uses only stdlib.

```python
@dataclass
class Config:
    repo: str                          # "owner/repo"
    github_token: str
    release_tag: str                   # e.g. "v1.2.0"
    release_name: str                  # e.g. "v1.2.0" or "Release 1.2.0"
    release_id: str                    # numeric GitHub release ID, may be empty
    default_branch: str                # e.g. "main"
    llm_providers: list[str]           # ["groq", "gemini"]
    llm_api_keys: list[str]            # one per provider
    llm_model: str                     # optional model override for first provider
    language: str                      # "english" | "italian" | "french" | "spanish" | "german"
    update_changelog_file: bool        # whether to commit CHANGELOG.md
    changelog_file_path: str           # default "CHANGELOG.md"
    max_commits: int                   # default 100
    max_prs: int                       # default 30
    max_eval_retries: int              # default 1

    @classmethod
    def from_env(cls) -> "Config":
        ...
```

Validation rules:
- `release_tag` must not be empty
- `llm_providers` and `llm_api_keys` must have the same length after parsing
- `language` must be one of the supported values; fall back to `"english"` with a warning if unknown
- `max_commits`, `max_prs`, `max_eval_retries` must be positive integers

### 7.2 `exceptions.py`

```python
class ChangelogError(Exception):
    """Base exception for all domain errors."""
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")

class GitHubAPIError(ChangelogError): ...
class LLMError(ChangelogError): ...
class PublishError(ChangelogError): ...
class ConfigError(ChangelogError): ...
```

Exit codes used in `generate.py`:
- `1` — domain error (ChangelogError subclass)
- `2` — unexpected error (bug)

### 7.3 `github_client.py`

All GitHub REST API calls. Uses only `requests`. Raises `GitHubAPIError` on non-2xx responses.

#### Methods

**`get_previous_tag(current_tag: str) -> str | None`**

Calls `GET /repos/{repo}/tags` (paginated) and returns the tag immediately before `current_tag` in the list. Returns `None` if `current_tag` is the first tag ever. Tag ordering follows the GitHub API order (most recent first).

**`get_commits_between(base: str | None, head: str, max_commits: int) -> list[CommitInfo]`**

If `base` is `None` (first release): calls `GET /repos/{repo}/commits?sha={head}&per_page=100` and returns up to `max_commits` commits.

Otherwise: calls `GET /repos/{repo}/compare/{base}...{head}` and extracts `commits` from the response. Truncates to `max_commits`.

`CommitInfo` is a dataclass:
```python
@dataclass
class CommitInfo:
    sha: str
    message: str        # full commit message (subject + body)
    author: str         # login or name
    url: str
```

**`get_merged_prs(base: str | None, head: str, max_prs: int) -> list[PRInfo]`**

Uses the compare endpoint to get the list of SHAs, then for each SHA calls `GET /repos/{repo}/commits/{sha}/pulls` to find associated PRs. Deduplicates by PR number. Returns only PRs that are merged (state=closed, merged_at is not null). Truncates to `max_prs`.

`PRInfo` is a dataclass:
```python
@dataclass
class PRInfo:
    number: int
    title: str
    body: str           # PR description, may be empty
    labels: list[str]   # label names
    url: str
    author: str
```

**`update_release_body(release_id: str, body: str) -> None`**

Calls `PATCH /repos/{repo}/releases/{release_id}` with `{"body": body}`. Raises `PublishError` on failure.

**`get_or_create_release_by_tag(tag: str, body: str) -> None`**

Used when `release_id` is empty (tag push trigger without a release object). Tries `GET /repos/{repo}/releases/tags/{tag}`. If found, calls `update_release_body`. If not found, calls `POST /repos/{repo}/releases` to create it with `tag_name=tag` and the given body.

**`get_file_contents(path: str) -> tuple[str, str]`**

Returns `(content_decoded, sha)` for `GET /repos/{repo}/contents/{path}` on the default branch. Returns `("", "")` if 404.

**`update_file_contents(path: str, content: str, sha: str | None, message: str) -> None`**

Calls `PUT /repos/{repo}/contents/{path}` with the base64-encoded content and optionally the existing SHA. Used to commit `CHANGELOG.md`.

#### HTTP behaviour

- All requests include `Authorization: Bearer {token}` and `Accept: application/vnd.github+json`
- Retry logic: up to 3 retries with exponential backoff (1s, 2s, 4s) on 5xx or connection errors
- On 403 with `X-RateLimit-Remaining: 0`, raise `GitHubAPIError` with code `RATE_LIMITED` and include reset time in message
- Timeout: 30 seconds per request

### 7.4 `classifier.py`

Classifies commits and PRs into semantic categories using heuristics (no LLM call, no external dependencies).

```python
@dataclass
class ClassifiedChanges:
    breaking: list[str]    # human-readable descriptions
    features: list[str]
    fixes: list[str]
    performance: list[str]
    docs: list[str]
    refactor: list[str]
    chore: list[str]
    other: list[str]
```

#### Classification logic

Priority order (first match wins):

1. **Breaking change**: PR label contains `breaking-change` OR commit message contains `BREAKING CHANGE:` or `!:` (conventional commits breaking indicator) OR PR title starts with `feat!:` / `fix!:` etc.

2. **Feature**: PR label is `feature`, `enhancement`, `feat` OR commit message starts with `feat:`, `feat(`, `feature:` OR PR title starts with `feat:` / `feature:`

3. **Fix**: PR label is `bug`, `fix`, `bugfix` OR commit message starts with `fix:`, `fix(`, `bugfix:` OR PR title starts with `fix:`

4. **Performance**: PR label is `performance`, `perf` OR commit message starts with `perf:`, `perf(`

5. **Docs**: PR label is `documentation`, `docs` OR commit message starts with `docs:`, `doc:`

6. **Refactor**: commit message starts with `refactor:`, `refactor(`

7. **Chore**: commit message starts with `chore:`, `chore(`, `ci:`, `build:`, `deps:` OR PR label is `dependencies`, `chore`, `ci`

8. **Other**: anything not matched above

Classification uses PR data preferentially over commit data when a PR is associated with a commit. The human-readable description is built as:
- If PR exists: `{PR title} (#{PR number})` with URL
- Else: first line of commit message with SHA (short, 7 chars)

Merge commits (`Merge pull request #N` or `Merge branch`) are skipped unless no other data is available.

### 7.5 `prompt.py`

Builds the LLM prompts. No external dependencies.

#### `get_system_prompt() -> str`

Returns the system prompt (see [Section 9](#9-prompt-engineering)).

#### `build_generation_prompt(classified, release_tag, release_name, previous_tag, language, repo) -> str`

Builds the user prompt for changelog generation. Includes:
- Release metadata (tag, name, previous tag, repo)
- Language instruction
- Classified changes grouped by category, formatted as a structured list
- Output format instructions (see [Section 9.1](#91-generation-prompt))

#### `build_evaluation_prompt(changelog_body, classified, language) -> str`

Builds the user prompt for self-evaluation. Includes:
- The generated changelog (full text)
- The raw classified changes (all categories)
- Instructions to check coverage and quality (see [Section 9.2](#92-self-evaluation-prompt))

### 7.6 `providers.py`

Identical architecture to `ai-pr-reviewer`. Manages multi-provider LLM calls with fallback and key rotation.

#### Supported providers

| Provider | Free tier | Default model |
|----------|-----------|---------------|
| `groq` | Yes | `llama-3.3-70b-versatile` |
| `gemini` | Yes | `gemini-2.0-flash` |
| `anthropic` | No | `claude-sonnet-4-5` |
| `openai` | No | `gpt-4o-mini` |

#### `get_provider(name, api_key, model) -> Provider`

Returns a `Provider` dataclass:
```python
@dataclass
class Provider:
    name: str
    api_key: str
    model: str
    endpoint: str
    headers: dict
    request_builder: Callable[[str, str, str], dict]  # (system, user, model) -> request body
    response_extractor: Callable[[dict], str]          # response json -> text
```

#### `call_llm_with_fallback(provider_chain, user) -> str`

Iterates through `provider_chain` (list of `(Provider, system_prompt)` tuples). For each provider:
- Builds the request body
- Makes the POST request (timeout 60s)
- On success: returns the extracted text
- On `requests.RequestException`, HTTP 4xx/5xx, or empty response: logs a warning and tries the next provider

If all providers fail, raises `LLMError` with code `ALL_PROVIDERS_FAILED`.

Per-provider retry: up to 2 retries with 2s delay on 5xx or timeout, no retry on 4xx.

### 7.7 `evaluator.py`

Performs self-evaluation of the generated changelog.

```python
class Evaluator:
    def __init__(self, provider_chain: list[tuple[Provider, str]]) -> None: ...

    def evaluate_and_refine(
        self,
        changelog_body: str,
        classified: ClassifiedChanges,
        language: str,
        max_retries: int,
    ) -> str:
        ...
```

#### Logic

1. Call LLM with the evaluation prompt (see [Section 9.2](#92-self-evaluation-prompt))
2. Parse the JSON response to extract `{"ok": bool, "feedback": str, "missing": list[str]}`
3. If `ok` is `true` → return `changelog_body` unchanged
4. If `ok` is `false` and retries remain → rebuild the generation prompt including `feedback` and `missing` as additional context, call LLM again, decrement retry counter, loop back to step 1
5. If `ok` is `false` and no retries remain → log a warning and return the last generated body (never block publishing)

The evaluation response must be valid JSON. If parsing fails, treat as `ok: true` and log a warning (fail-safe: never block publishing due to evaluator failure).

### 7.8 `publisher.py`

```python
class Publisher:
    def __init__(self, github: GitHubClient, cfg: Config) -> None: ...

    def publish(self, changelog_body: str, release_tag: str) -> None:
        ...
```

#### Logic

1. Update the GitHub Release body:
   - If `cfg.release_id` is not empty: call `github.update_release_body(cfg.release_id, changelog_body)`
   - If empty: call `github.get_or_create_release_by_tag(release_tag, changelog_body)`

2. If `cfg.update_changelog_file` is `True`:
   - Call `github.get_file_contents(cfg.changelog_file_path)` to get existing content and SHA
   - Prepend the new changelog section to the existing content
   - Call `github.update_file_contents(...)` with the commit message `chore: update CHANGELOG.md for {release_tag} [skip ci]`
   - The `[skip ci]` tag prevents triggering another workflow run

---

## 8. Pipeline Logic

```
main()
  │
  ├── 1. Config.from_env()
  │
  ├── 2. GitHubClient.get_previous_tag(release_tag)
  │        → previous_tag (str | None)
  │
  ├── 3. GitHubClient.get_commits_between(previous_tag, release_tag)
  │        → commits: list[CommitInfo]
  │
  ├── 4. GitHubClient.get_merged_prs(previous_tag, release_tag)
  │        → prs: list[PRInfo]
  │
  ├── 5. [early exit if commits == [] and prs == []]
  │
  ├── 6. Classifier.classify(commits, prs)
  │        → classified: ClassifiedChanges
  │
  ├── 7. build_generation_prompt(classified, ...)
  │
  ├── 8. call_llm_with_fallback(provider_chain, generation_prompt)
  │        → changelog_body: str
  │
  ├── 9. [if max_eval_retries > 0]
  │        Evaluator.evaluate_and_refine(changelog_body, classified, ...)
  │           → changelog_body: str (possibly regenerated)
  │
  └── 10. Publisher.publish(changelog_body, release_tag)
           ├── update GitHub Release body
           └── [if update_changelog_file] commit CHANGELOG.md
```

---

## 9. Prompt Engineering

### 9.1 Generation prompt

#### System prompt

```
You are an expert technical writer specialising in software release notes and changelogs.
Your task is to generate clear, accurate, and well-structured changelogs for software releases.
Write for a technical audience: developers who need to understand what changed and whether they need to take action.
Be concise but complete. Never invent changes that are not in the provided data.
```

#### User prompt structure

```
Generate a changelog for release {release_tag} of {repo}.
{previous_tag context: "This release covers changes since {previous_tag}." or "This is the first release."}

Write the changelog in {LANGUAGE}.

## Changes to document

### Breaking changes
{list of breaking change descriptions, one per line, or "(none)"}

### New features
{list of feature descriptions}

### Bug fixes
{list of fix descriptions}

### Performance improvements
{list of perf descriptions, or omit section if empty}

### Documentation
{list of docs descriptions, or omit section if empty}

### Refactoring
{list of refactor descriptions, or omit section if empty}

### Chores and maintenance
{list of chore descriptions, or omit section if empty}

### Other changes
{list of other descriptions, or omit section if empty}

## Output format

Produce ONLY the changelog body in Markdown. Do not include a preamble or conclusion.
Use the following structure:

## What's Changed in {release_tag}

> {one-sentence summary of the most important change in this release}

{If breaking changes exist, open with:}
### ⚠️ Breaking Changes
- {description}

### ✨ New Features
- {description}

### 🐛 Bug Fixes
- {description}

### 🚀 Performance
- {description}  [omit section if empty]

### 📚 Documentation
- {description}  [omit section if empty]

### 🔧 Maintenance
- {description combining refactor + chore + other, omit if empty}

---
*Generated by [ai-changelog-generator](https://github.com/AndreaBonn/ai-changelog-generator)*

Rules:
- Omit sections that have no items.
- Keep each bullet to one line.
- If a PR number is available, include it as "(#N)" at the end of the line.
- Do not fabricate changes.
- The summary sentence must reflect the actual content.
{If feedback from previous evaluation:}
- Previous evaluation feedback to address: {feedback}
- Missing items to include: {missing list}
```

### 9.2 Self-evaluation prompt

#### System prompt

Same as generation system prompt.

#### User prompt

```
You are reviewing a generated changelog for correctness and completeness.

## Generated changelog
{changelog_body}

## Source data (ground truth)

### Breaking changes (must all appear in changelog)
{list or "(none)"}

### New features (should appear in changelog)
{list or "(none)"}

### Bug fixes (should appear in changelog)
{list or "(none)"}

### Other changes
{list or "(none)"}

## Your task

Check whether the changelog:
1. Includes ALL breaking changes — this is mandatory
2. Includes all significant features and bug fixes
3. Does not contain invented or hallucinated items not present in the source data
4. Has the correct overall tone and language

Respond ONLY with valid JSON, no markdown fences, no explanation:
{
  "ok": true/false,
  "feedback": "brief description of issues found, or empty string if ok",
  "missing": ["item 1 that was missing", "item 2 that was missing"]
}

Set "ok" to true if the changelog is acceptable. Set to false only if:
- A breaking change is missing, OR
- More than 2 significant features or fixes are missing, OR
- There are clearly hallucinated items

Do not be overly strict. Minor omissions of chores or refactoring are acceptable.
```

---

## 10. LLM Provider System

The `providers.py` module implements all four providers using only `requests`. Below are the exact API call structures for each.

### Groq

```
POST https://api.groq.com/openai/v1/chat/completions
Headers:
  Authorization: Bearer {api_key}
  Content-Type: application/json
Body:
  {
    "model": "llama-3.3-70b-versatile",
    "messages": [
      {"role": "system", "content": "{system_prompt}"},
      {"role": "user", "content": "{user_prompt}"}
    ],
    "max_tokens": 2048,
    "temperature": 0.3
  }
Response extraction: response["choices"][0]["message"]["content"]
```

### Gemini

```
POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}
Headers:
  Content-Type: application/json
Body:
  {
    "system_instruction": {"parts": [{"text": "{system_prompt}"}]},
    "contents": [{"role": "user", "parts": [{"text": "{user_prompt}"}]}],
    "generationConfig": {"maxOutputTokens": 2048, "temperature": 0.3}
  }
Response extraction: response["candidates"][0]["content"]["parts"][0]["text"]
```

### Anthropic

```
POST https://api.anthropic.com/v1/messages
Headers:
  x-api-key: {api_key}
  anthropic-version: 2023-06-01
  Content-Type: application/json
Body:
  {
    "model": "claude-sonnet-4-5",
    "max_tokens": 2048,
    "system": "{system_prompt}",
    "messages": [{"role": "user", "content": "{user_prompt}"}]
  }
Response extraction: response["content"][0]["text"]
```

### OpenAI

```
POST https://api.openai.com/v1/chat/completions
Headers:
  Authorization: Bearer {api_key}
  Content-Type: application/json
Body:
  {
    "model": "gpt-4o-mini",
    "messages": [
      {"role": "system", "content": "{system_prompt}"},
      {"role": "user", "content": "{user_prompt}"}
    ],
    "max_tokens": 2048,
    "temperature": 0.3
  }
Response extraction: response["choices"][0]["message"]["content"]
```

### Temperature

Use `temperature=0.3` for generation (low randomness, consistent output) and `temperature=0.1` for evaluation (deterministic scoring).

---

## 11. GitHub API Usage

All calls use `https://api.github.com`. Token required: `GITHUB_TOKEN` (standard Actions token).

### Required token permissions

```yaml
permissions:
  contents: write       # to commit CHANGELOG.md (if update_changelog_file: true)
  releases: write       # to update the release body
```

When `update_changelog_file` is `false`, only `releases: write` is needed.

### API endpoints used

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/repos/{repo}/tags` | List tags to find previous tag |
| GET | `/repos/{repo}/compare/{base}...{head}` | Get commits and diff stats between tags |
| GET | `/repos/{repo}/commits?sha={head}` | Get commits for first release (no base) |
| GET | `/repos/{repo}/commits/{sha}/pulls` | Find PRs associated with a commit |
| PATCH | `/repos/{repo}/releases/{id}` | Update release body |
| GET | `/repos/{repo}/releases/tags/{tag}` | Get release by tag (tag push trigger) |
| POST | `/repos/{repo}/releases` | Create release (if none exists for tag) |
| GET | `/repos/{repo}/contents/{path}` | Read CHANGELOG.md |
| PUT | `/repos/{repo}/contents/{path}` | Commit updated CHANGELOG.md |

---

## 12. Output Format

The generated changelog body (Markdown) follows this structure:

```markdown
## What's Changed in v1.2.0

> Added support for multi-provider fallback and improved error reporting.

### ⚠️ Breaking Changes
- Removed `legacy_mode` configuration option (#42)

### ✨ New Features
- Multi-provider LLM fallback with key rotation (#38)
- Added Italian and French output language support (#39)

### 🐛 Bug Fixes
- Fixed rate limit handling on Groq provider (#41)
- Corrected token count calculation for large diffs (#40)

### 🔧 Maintenance
- Upgraded dependencies to latest versions (#43)
- Improved test coverage to 94% (#44)

---
*Generated by [ai-changelog-generator](https://github.com/AndreaBonn/ai-changelog-generator)*
```

Rules enforced by the prompt:
- Sections with no items are omitted entirely
- Breaking changes section always appears first if non-empty
- The `⚠️` emoji before "Breaking Changes" is always present when there are breaking changes
- Each bullet is one line maximum
- PR number in format `(#N)` at end of line when available
- The summary sentence (blockquote) is always present

---

## 13. Inputs Reference

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `llm_provider` | No | `groq` | Comma-separated provider list for fallback |
| `llm_api_key` | **Yes** | — | Comma-separated API keys, one per provider entry |
| `llm_model` | No | `""` | Model override for the first provider |
| `github_token` | **Yes** | — | GitHub token (`secrets.GITHUB_TOKEN`) |
| `language` | No | `english` | Output language |
| `update_changelog_file` | No | `false` | Whether to commit `CHANGELOG.md` |
| `changelog_file_path` | No | `CHANGELOG.md` | Path to the changelog file |
| `max_commits` | No | `100` | Max commits to include in LLM context |
| `max_prs` | No | `30` | Max PRs to include in LLM context |
| `max_eval_retries` | No | `1` | Self-evaluation retry count (0 to disable) |

---

## 14. Environment Variables

All injected by `action.yml` from inputs and GitHub context:

| Variable | Source |
|----------|--------|
| `LLM_PROVIDER` | `inputs.llm_provider` |
| `LLM_API_KEY` | `inputs.llm_api_key` |
| `LLM_MODEL` | `inputs.llm_model` |
| `GITHUB_TOKEN` | `inputs.github_token` |
| `CHANGELOG_LANGUAGE` | `inputs.language` |
| `UPDATE_CHANGELOG_FILE` | `inputs.update_changelog_file` |
| `CHANGELOG_FILE_PATH` | `inputs.changelog_file_path` |
| `MAX_COMMITS` | `inputs.max_commits` |
| `MAX_PRS` | `inputs.max_prs` |
| `MAX_EVAL_RETRIES` | `inputs.max_eval_retries` |
| `REPO_FULL_NAME` | `github.repository` |
| `RELEASE_TAG` | `github.event.release.tag_name` or `github.ref_name` |
| `RELEASE_NAME` | `github.event.release.name` or `github.ref_name` |
| `RELEASE_ID` | `github.event.release.id` (empty on tag push) |
| `DEFAULT_BRANCH` | `github.event.repository.default_branch` |

---

## 15. Error Handling and Exit Codes

| Exit code | Meaning |
|-----------|---------|
| `0` | Success |
| `1` | Domain error (ChangelogError subclass) — check logs |
| `2` | Unexpected error — likely a bug, report it |

### Error codes used in ChangelogError subclasses

| Code | Class | Meaning |
|------|-------|---------|
| `CONFIG_INVALID` | ConfigError | Missing or invalid configuration |
| `GITHUB_API_ERROR` | GitHubAPIError | Non-2xx from GitHub API |
| `RATE_LIMITED` | GitHubAPIError | GitHub rate limit exceeded |
| `ALL_PROVIDERS_FAILED` | LLMError | All LLM providers failed |
| `PUBLISH_FAILED` | PublishError | Could not update release or CHANGELOG.md |

### Fail-safe principles

- If self-evaluation fails (JSON parse error, LLM error): log warning, continue with current changelog body, never abort
- If `CHANGELOG.md` commit fails: log warning, do not abort (release body was already updated)
- If no commits and no PRs are found: log info and exit 0 (no-op, not an error)

---

## 16. Test Suite

Target: **≥ 90% line coverage**.

All tests in `tests/`. Use `pytest` and `unittest.mock`. No real network calls in tests.

### `test_config.py`
- Valid env parsing
- Provider/key list mismatch raises ConfigError
- Unknown language falls back to "english" with warning
- Missing required vars raise ConfigError
- Boolean parsing for `update_changelog_file`

### `test_classifier.py`
- Breaking change detection via label
- Breaking change detection via `BREAKING CHANGE:` in commit message
- Breaking change detection via `!:` conventional commit syntax
- Feature detection via PR label and commit prefix
- Fix detection via PR label and commit prefix
- Merge commit skipping
- Fallback to "other" for unrecognised patterns
- PR data takes priority over commit data

### `test_prompt.py`
- Generation prompt includes release tag
- Generation prompt includes previous tag context
- Generation prompt includes all non-empty categories
- Generation prompt omits empty categories
- Generation prompt includes feedback when provided
- Evaluation prompt includes all classified items
- Evaluation prompt includes changelog body

### `test_providers.py`
- Groq request body structure
- Gemini request body structure
- Anthropic request body structure
- OpenAI request body structure
- Model override applies only to first provider
- Fallback to second provider on first provider 500
- Fallback to second provider on ConnectionError
- No retry on 4xx
- Raises LLMError when all providers fail
- Empty response from provider triggers fallback

### `test_evaluator.py`
- Returns original body when LLM responds `{"ok": true, ...}`
- Regenerates when LLM responds `{"ok": false, ...}`
- Stops after `max_retries` even if still failing
- Returns last body (never aborts) when retries exhausted
- Handles invalid JSON from LLM gracefully (treat as ok=true)
- Feedback is passed to regeneration prompt

### `test_publisher.py`
- Calls `update_release_body` when `release_id` is set
- Calls `get_or_create_release_by_tag` when `release_id` is empty
- Commits CHANGELOG.md when `update_changelog_file` is True
- Skips CHANGELOG.md commit when `update_changelog_file` is False
- CHANGELOG.md commit includes `[skip ci]` in message
- Logs warning and continues if CHANGELOG.md commit fails

### `test_github_client.py`
- `get_previous_tag` returns second tag in list
- `get_previous_tag` returns None for first release
- `get_commits_between` uses compare endpoint when base is set
- `get_commits_between` uses commits endpoint when base is None
- `get_commits_between` truncates to `max_commits`
- `get_merged_prs` deduplicates by PR number
- `get_merged_prs` skips non-merged PRs
- HTTP 4xx raises GitHubAPIError immediately (no retry)
- HTTP 5xx retries up to 3 times
- Rate limit response raises GitHubAPIError with code RATE_LIMITED

### `test_generate.py`
- Full happy path integration test (all mocked)
- Early exit when no commits and no PRs found
- Evaluation step is skipped when `max_eval_retries=0`
- Exit code 1 on ChangelogError
- Exit code 2 on unexpected exception

---

## 17. CI/CD Pipeline

### `.github/workflows/test.yml`

Triggers on: `push` to any branch, `pull_request` to `main`.

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.11', '3.12']
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pip install uv && uv sync --dev
      - run: uv run pytest tests/ -v --cov=changelog --cov-report=json
      - run: uv run ruff check changelog/ tests/
      - run: uv run ruff format --check changelog/ tests/
      - run: uv run mypy changelog/
      - name: Update badges
        run: python scripts/update_badges.py   # generates badges/test-badge.json and coverage-badge.json
        if: github.ref == 'refs/heads/main'
      - name: Commit badges
        uses: stefanzweifel/git-auto-commit-action@v5
        with:
          commit_message: "chore: update badges [skip ci]"
          file_pattern: badges/*.json
        if: github.ref == 'refs/heads/main'
```

---

## 18. Packaging and Tooling

### `pyproject.toml`

```toml
[project]
name = "ai-changelog-generator"
version = "1.0.0"
description = "AI-powered changelog generator GitHub Action"
requires-python = ">=3.11"
dependencies = ["requests>=2.32"]

[project.scripts]
ai-changelog = "generate:entrypoint"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.mypy]
strict = true
python_version = "3.11"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v --tb=short"

[tool.coverage.run]
source = ["changelog"]
branch = true

[tool.coverage.report]
fail_under = 90
```

### `requirements.txt`

```
requests>=2.32
```

Dev dependencies (in `pyproject.toml` optional group `dev`):
```
pytest, pytest-cov, ruff, mypy, types-requests, uv
```

---

## 19. Security Policy

Create `SECURITY.md` and `SECURITY.it.md` following the same structure as `ai-pr-reviewer/SECURITY.md`.

Key points to document:
- API keys are never logged or included in any output
- The generated changelog is based only on commit messages, PR titles, PR bodies, and PR labels — no code content is sent to the LLM
- The `GITHUB_TOKEN` is only used for the specific repo where the action runs
- No data is stored or transmitted by this action beyond the LLM provider call
- Users should review the LLM provider's privacy policy
- The `[skip ci]` tag on CHANGELOG.md commits prevents infinite workflow loops
- Supported versions and vulnerability reporting process

---

## 20. README Requirements

The README must be bilingual (`README.md` in English, `README.it.md` in Italian).

Required sections (follow `ai-pr-reviewer` README structure):

1. **Title + badges** (CI, Tests, Coverage, Ruff, License, Security Policy, GitHub Actions Marketplace)
2. **Language toggle** (English | Italiano)
3. **Quick Start** — 3-step setup (add secret, create workflow, publish release)
4. **Minimal workflow example** — copy-paste ready YAML
5. **Inputs table** — all inputs with required/default/description
6. **Supported Providers table** — with cost, default model, speed, quality columns
7. **Getting API Keys** — links to Groq, Gemini, Anthropic, OpenAI
8. **Provider Fallback** — multi-provider and multi-key examples
9. **Output format** — changelog structure with example screenshot (`assets/changelog-example.png`)
10. **Self-evaluation** — brief explanation of the quality check step
11. **update_changelog_file** — explanation of the optional CHANGELOG.md commit
12. **Permissions** — required GitHub token permissions
13. **Privacy & Security** — what data is sent to the LLM
14. **Limitations** — LLM accuracy caveat, static analysis only, first release detection
15. **Support** — star link + issue link
16. **License** — Apache 2.0

---

## 21. Behavioural Constraints for Implementation

The following constraints must be respected throughout the implementation. They reflect the code style and principles of the existing `ai-pr-reviewer` project.

1. **Zero production dependencies beyond `requests`.** Do not introduce `httpx`, `pydantic`, `langchain`, or any other library in `requirements.txt`.

2. **All modules in `changelog/` must be importable with only stdlib + requests.** No optional imports that silently degrade behaviour.

3. **No `print()` statements anywhere.** Use `logging` exclusively, with the logger named `"ai-changelog-generator"`.

4. **All public functions and classes must have docstrings.**

5. **All dataclasses use `@dataclass` from stdlib**, not Pydantic BaseModel.

6. **Type hints are mandatory** on all function signatures. The codebase must pass `mypy --strict`.

7. **`Config.from_env()` is the single source of truth** for reading environment variables. No other module may call `os.environ` directly.

8. **The action must be idempotent**: running it twice for the same release must produce the same result (overwrite, not append, the release body).

9. **The `[skip ci]` tag is mandatory** on any commit made by the action to prevent loop triggers.

10. **The self-evaluation step must never block publishing.** Any failure in the evaluator (exception, invalid JSON, LLM error) must be caught, logged as a warning, and execution must continue with the current changelog body.

11. **All GitHub API calls must include a `User-Agent` header**: `ai-changelog-generator/1.0`.

12. **Token and API keys must never appear in log output**, even partially. The logging must redact them if they somehow end up in an exception message.

13. **The action must handle the first release gracefully** (no previous tag) by using all commits up to the current tag.

14. **Code style**: follow the same patterns as `ai-pr-reviewer` — module-level loggers, explicit exception chaining (`raise X from Y`), no bare `except:`, no mutable default arguments.

15. **Test file naming** follows `test_{module_name}.py`. Each test function name starts with `test_` and describes the specific behaviour being tested, not the method name.
