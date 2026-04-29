"""Tests for changelog.classifier."""

from __future__ import annotations

from changelog.classifier import Classifier
from changelog.github_client import CommitInfo, PRInfo


def _commit(message: str, sha: str = "abc1234") -> CommitInfo:
    return CommitInfo(sha=sha, message=message, author="dev", url="")


def _pr(
    title: str,
    number: int = 1,
    labels: list[str] | None = None,
    body: str = "",
) -> PRInfo:
    return PRInfo(
        number=number,
        title=title,
        body=body,
        labels=labels or [],
        url="",
        author="dev",
    )


class TestBreakingChangeDetection:
    def test_breaking_via_label(self) -> None:
        classifier = Classifier()
        result = classifier.classify([], [_pr("update API", labels=["breaking-change"])])
        assert len(result.breaking) == 1

    def test_breaking_via_commit_message_keyword(self) -> None:
        classifier = Classifier()
        result = classifier.classify(
            [_commit("refactor: change API\n\nBREAKING CHANGE: removed v1")], []
        )
        assert len(result.breaking) == 1

    def test_breaking_via_conventional_bang(self) -> None:
        classifier = Classifier()
        result = classifier.classify([], [_pr("feat!: remove legacy endpoint")])
        assert len(result.breaking) == 1

    def test_breaking_via_scoped_bang(self) -> None:
        classifier = Classifier()
        result = classifier.classify([_commit("fix(api)!: change response format")], [])
        assert len(result.breaking) == 1

    def test_breaking_change_keyword_case_insensitive(self) -> None:
        classifier = Classifier()
        result = classifier.classify(
            [_commit("refactor: change API\n\nbreaking change: removed v1")], []
        )
        assert len(result.breaking) == 1


class TestFeatureDetection:
    def test_feature_via_pr_label(self) -> None:
        classifier = Classifier()
        result = classifier.classify([], [_pr("add login", labels=["enhancement"])])
        assert len(result.features) == 1

    def test_feature_via_commit_prefix(self) -> None:
        classifier = Classifier()
        result = classifier.classify([_commit("feat: add dark mode")], [])
        assert len(result.features) == 1

    def test_feature_via_scoped_prefix(self) -> None:
        classifier = Classifier()
        result = classifier.classify([_commit("feat(ui): add sidebar")], [])
        assert len(result.features) == 1


class TestFixDetection:
    def test_fix_via_pr_label(self) -> None:
        classifier = Classifier()
        result = classifier.classify([], [_pr("fix crash", labels=["bug"])])
        assert len(result.fixes) == 1

    def test_fix_via_commit_prefix(self) -> None:
        classifier = Classifier()
        result = classifier.classify([_commit("fix: null pointer on login")], [])
        assert len(result.fixes) == 1


class TestOtherCategories:
    def test_perf_via_commit(self) -> None:
        classifier = Classifier()
        result = classifier.classify([_commit("perf: reduce query time")], [])
        assert len(result.performance) == 1

    def test_docs_via_label(self) -> None:
        classifier = Classifier()
        result = classifier.classify([], [_pr("update readme", labels=["documentation"])])
        assert len(result.docs) == 1

    def test_chore_via_commit(self) -> None:
        classifier = Classifier()
        result = classifier.classify([_commit("chore: update deps")], [])
        assert len(result.chore) == 1

    def test_perf_via_pr_label(self) -> None:
        classifier = Classifier()
        result = classifier.classify([], [_pr("speed up query", labels=["performance"])])
        assert len(result.performance) == 1

    def test_chore_via_pr_label(self) -> None:
        classifier = Classifier()
        result = classifier.classify([], [_pr("bump deps", labels=["dependencies"])])
        assert len(result.chore) == 1

    def test_docs_via_commit_doc_prefix(self) -> None:
        classifier = Classifier()
        result = classifier.classify([_commit("doc: update API guide")], [])
        assert len(result.docs) == 1

    def test_refactor_via_commit(self) -> None:
        classifier = Classifier()
        result = classifier.classify([_commit("refactor: extract helper")], [])
        assert len(result.refactor) == 1


class TestEdgeCases:
    def test_merge_commit_skipped(self) -> None:
        classifier = Classifier()
        result = classifier.classify([_commit("Merge pull request #42 from dev/feat")], [])
        assert all(
            len(getattr(result, cat)) == 0 for cat in ("breaking", "features", "fixes", "other")
        )

    def test_unrecognised_falls_to_other(self) -> None:
        classifier = Classifier()
        result = classifier.classify([_commit("random message with no prefix")], [])
        assert len(result.other) == 1

    def test_pr_data_takes_priority_over_commit(self) -> None:
        classifier = Classifier()
        pr = _pr("feat: new login", number=10, labels=["enhancement"])
        commit = _commit("feat: new login", sha="aaa1111")
        result = classifier.classify([commit], [pr])
        assert len(result.features) >= 1
        assert any("(#10)" in item for item in result.features)

    def test_description_includes_pr_number(self) -> None:
        classifier = Classifier()
        result = classifier.classify([], [_pr("fix: typo", number=99, labels=["bug"])])
        assert "(#99)" in result.fixes[0]

    def test_description_includes_short_sha(self) -> None:
        classifier = Classifier()
        result = classifier.classify([_commit("fix: typo", sha="abcdef1234567")], [])
        assert "(abcdef1)" in result.fixes[0]
