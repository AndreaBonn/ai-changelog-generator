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
    from changelog.classifier import Classifier
    from changelog.config import Config
    from changelog.evaluator import Evaluator
    from changelog.github_client import GitHubClient
    from changelog.prompt import build_generation_prompt, get_system_prompt
    from changelog.providers import call_llm_with_fallback, get_provider
    from changelog.publisher import Publisher

    cfg = Config.from_env()
    github = GitHubClient(token=cfg.github_token, repo=cfg.repo)

    log.info(
        "Generating changelog for %s on %s (providers=%s, language=%s)",
        cfg.release_tag,
        cfg.repo,
        ",".join(cfg.llm_providers),
        cfg.language,
    )

    previous_tag = github.get_previous_tag(cfg.release_tag)
    log.info("Comparing %s...%s", previous_tag or "<initial>", cfg.release_tag)

    commits = github.get_commits_between(previous_tag, cfg.release_tag, max_commits=cfg.max_commits)
    prs = github.get_merged_prs(previous_tag, cfg.release_tag, max_prs=cfg.max_prs)
    log.info("Fetched %d commits and %d merged PRs.", len(commits), len(prs))

    if not commits and not prs:
        log.info("No commits or PRs found — skipping changelog generation.")
        return

    classifier = Classifier()
    classified = classifier.classify(commits, prs)
    log.info(
        "Classified: %d breaking, %d features, %d fixes, %d other.",
        len(classified.breaking),
        len(classified.features),
        len(classified.fixes),
        len(classified.other),
    )

    provider_chain = []
    for i, (name, key) in enumerate(zip(cfg.llm_providers, cfg.llm_api_keys, strict=True)):
        model = cfg.llm_model if i == 0 else ""
        provider = get_provider(name=name, api_key=key, model=model, max_tokens=cfg.max_tokens)
        system_prompt = get_system_prompt()
        provider_chain.append((provider, system_prompt))

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

    if cfg.max_eval_retries > 0:
        evaluator = Evaluator(provider_chain=provider_chain)
        changelog_body = evaluator.evaluate_and_refine(
            changelog_body=changelog_body,
            classified=classified,
            language=cfg.language,
            max_retries=cfg.max_eval_retries,
            release_tag=cfg.release_tag,
            release_name=cfg.release_name,
            previous_tag=previous_tag,
            repo=cfg.repo,
        )

    publisher = Publisher(github=github, cfg=cfg)
    publisher.publish(changelog_body=changelog_body, release_tag=cfg.release_tag)
    log.info("Changelog published successfully.")


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
