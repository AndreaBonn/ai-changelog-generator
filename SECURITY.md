**English** | [Italiano](SECURITY.it.md)

# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 1.x | Yes |

## Reporting a vulnerability

To report a security vulnerability, use [GitHub Security Advisories](https://github.com/AndreaBonn/ai-changelog-generator/security/advisories/new). Do not open a public issue.

Include in your report:

- Description of the vulnerability
- Steps to reproduce
- Affected version(s)
- Potential impact

Response timeline:

- Acknowledgment within 72 hours
- Fix for critical vulnerabilities within 30 days
- Coordinated public disclosure after the fix is released

## Security measures

This project implements the following verifiable security practices:

- **API keys transmitted via headers, never in URLs**: all four LLM providers (Groq, Gemini, Anthropic, OpenAI) pass API keys exclusively through HTTP headers (`providers.py:160-163, 175-176, 190-194, 205-208`).
- **Environment variable isolation**: all configuration is read from environment variables in a single function, `Config.from_env()` (`config.py:37`). No other module accesses `os.environ`.
- **No secrets in logs**: the project uses `logging` exclusively (zero `print()` statements). API keys and tokens are never included in log messages.
- **Input validation at the boundary**: required environment variables are validated on startup with explicit error messages (`config.py:46-56`). Integer parameters are validated for range (`config.py:101-128`).
- **GitHub Actions SHA pinning**: all third-party actions in CI workflows are pinned to specific commit SHAs, not mutable tags (`action.yml:58`, `.github/workflows/test.yml:15-16`).
- **Dependency lockfile**: `uv.lock` is committed to the repository, ensuring reproducible builds.
- **Automated commit marker**: commits made by the action include `[skip ci]` to prevent recursive CI triggers (`publisher.py:45`).

## Security best practices for users

When configuring this action in your workflows:

- Store API keys as GitHub Actions secrets, never as plaintext in workflow files.
- Use a GitHub token with the minimum required permissions (`contents: write` for release updates).
- Pin the action to a specific commit SHA or release tag rather than a branch name.

## Out of scope

The following are not considered vulnerabilities for this project:

- Vulnerabilities in third-party dependencies that are already publicly disclosed (report these upstream).
- Quality or accuracy of LLM-generated changelog content.
- Rate limit exhaustion from normal usage patterns.
- Issues requiring physical access to the runner environment.
- Social engineering attacks.

## Acknowledgments

Security researchers who report valid vulnerabilities will be credited here upon request.

---

[Back to README](README.md)
