from standup_generator.config import GitLocalConfig
from standup_generator.sources.git_local import GitLocalSource


def _src(**kw):
    kw.setdefault("author_emails", ["me@x.com"])
    return GitLocalSource(GitLocalConfig(**kw))


def test_collects_only_my_commits_in_window(repo, window):
    r = _src(repos=[repo]).collect(window)
    assert r.errors == []
    assert {c.subject for c in r.commits} == {"OFF-12 add retry"}
    assert r.commits[0].repo == "svc"


def test_branch_from_source(repo, window):
    r = _src(repos=[repo]).collect(window)
    assert "feat/OFF-12-retry" in r.commits[0].branches


def test_missing_repo_reports_error_and_continues(repo, window, tmp_path):
    r = _src(repos=[tmp_path / "nope", repo]).collect(window)
    assert len(r.commits) == 1
    assert any("nope" in e for e in r.errors)


def test_non_git_dir_reports_error(window, tmp_path):
    d = tmp_path / "plain"
    d.mkdir()
    r = _src(repos=[d]).collect(window)
    assert r.commits == [] and any("plain" in e for e in r.errors)


def test_scan_dirs_finds_nested_repo(repo, window):
    r = _src(scan_dirs=[repo.parent.parent]).collect(window)
    assert {c.subject for c in r.commits} == {"OFF-12 add retry"}


def test_repo_listed_twice_is_deduplicated(repo, window):
    r = _src(repos=[repo], scan_dirs=[repo.parent]).collect(window)
    assert len(r.commits) == 1


def test_no_repos_is_info_not_error(window):
    r = _src(repos=[], scan_dirs=[]).collect(window)
    assert r.errors == [] and r.info


def test_no_author_email_is_error(repo, window, monkeypatch):
    src = GitLocalSource(GitLocalConfig(repos=[repo]), default_email=lambda: None)
    r = src.collect(window)
    assert r.errors == ["git_local: no author email — set sources.git_local.author_emails"]
