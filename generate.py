"""Entry point for the AI Changelog Generator GitHub Action."""

from __future__ import annotations

import logging
import sys

from changelog.exceptions import ChangelogError

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s | %(message)s",
)
log = logging.getLogger("ai-changelog-generator")


def main() -> None:
    """Run the changelog generation pipeline."""
    from changelog.config import Config

    cfg = Config.from_env()
    log.info(
        "Generating changelog for %s on %s (providers=%s, language=%s)",
        cfg.release_tag,
        cfg.repo,
        ",".join(cfg.llm_providers),
        cfg.language,
    )


def entrypoint() -> None:
    """Wrapper with error handling and exit codes."""
    try:
        main()
    except ChangelogError as exc:
        log.error("[%s] %s", exc.code, exc.message)
        sys.exit(1)
    except Exception as exc:
        log.critical(
            "Unexpected error — please report at "
            "https://github.com/AndreaBonn/ai-changelog-generator/issues. "
            "Details: %s: %s",
            type(exc).__name__,
            exc,
        )
        sys.exit(2)


if __name__ == "__main__":
    entrypoint()
