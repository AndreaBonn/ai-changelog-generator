"""Heuristic classifier for commits and PRs into semantic changelog categories."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from changelog.github_client import CommitInfo, PRInfo

MERGE_PATTERN = re.compile(r"^Merge (pull request #\d+|branch )")

BREAKING_LABELS = frozenset({"breaking-change", "breaking"})
FEATURE_LABELS = frozenset({"feature", "enhancement", "feat"})
FIX_LABELS = frozenset({"bug", "fix", "bugfix"})
PERF_LABELS = frozenset({"performance", "perf"})
DOCS_LABELS = frozenset({"documentation", "docs"})
CHORE_LABELS = frozenset({"dependencies", "chore", "ci"})


@dataclass
class ClassifiedChanges:
    """Commits and PRs grouped by semantic category."""

    breaking: list[str] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    fixes: list[str] = field(default_factory=list)
    performance: list[str] = field(default_factory=list)
    docs: list[str] = field(default_factory=list)
    refactor: list[str] = field(default_factory=list)
    chore: list[str] = field(default_factory=list)
    other: list[str] = field(default_factory=list)


class Classifier:
    """Classify commits and PRs into changelog categories using heuristics."""

    def classify(
        self,
        commits: list[CommitInfo],
        prs: list[PRInfo],
    ) -> ClassifiedChanges:
        """Classify all commits and PRs, preferring PR data when available."""
        result = ClassifiedChanges()
        for pr in prs:
            desc = f"{pr.title} (#{pr.number})"
            category = _classify_pr(pr)
            _append_to_category(result, category, desc)

        for commit in commits:
            if MERGE_PATTERN.match(commit.message):
                continue
            first_line = commit.message.split("\n", 1)[0].strip()
            short_sha = commit.sha[:7]
            desc = f"{first_line} ({short_sha})"
            category = _classify_commit_message(commit.message)
            _append_to_category(result, category, desc)

        return result


def _classify_pr(pr: PRInfo) -> str:
    """Classify a PR by labels first, then by title prefix."""
    label_names = {lb.lower() for lb in pr.labels}

    if label_names & BREAKING_LABELS:
        return "breaking"
    title_lower = pr.title.lower()
    if _has_breaking_indicator(title_lower):
        return "breaking"

    if label_names & FEATURE_LABELS:
        return "features"
    if label_names & FIX_LABELS:
        return "fixes"
    if label_names & PERF_LABELS:
        return "performance"
    if label_names & DOCS_LABELS:
        return "docs"
    if label_names & CHORE_LABELS:
        return "chore"

    return _classify_by_prefix(title_lower)


def _classify_commit_message(message: str) -> str:
    """Classify a commit by its message using conventional commit prefixes."""
    first_line = message.split("\n", 1)[0].strip().lower()

    if "BREAKING CHANGE:" in message.upper() or _has_breaking_indicator(first_line):
        return "breaking"

    return _classify_by_prefix(first_line)


def _has_breaking_indicator(text: str) -> bool:
    """Check for conventional commit breaking change markers."""
    return bool(re.match(r"^(feat|fix|chore|refactor|perf|docs|build|ci|test)(\(.+\))?!:", text))


def _classify_by_prefix(text: str) -> str:
    """Classify text by conventional commit prefix."""
    if re.match(r"^(feat|feature)(\(.+\))?:", text):
        return "features"
    if re.match(r"^(fix|bugfix)(\(.+\))?:", text):
        return "fixes"
    if re.match(r"^perf(\(.+\))?:", text):
        return "performance"
    if re.match(r"^(docs?|doc)(\(.+\))?:", text):
        return "docs"
    if re.match(r"^refactor(\(.+\))?:", text):
        return "refactor"
    if re.match(r"^(chore|ci|build|deps)(\(.+\))?:", text):
        return "chore"
    return "other"


def _append_to_category(result: ClassifiedChanges, category: str, desc: str) -> None:
    """Append a description to the appropriate category list."""
    getattr(result, category).append(desc)
