import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from standup_generator.models import TimeWindow

UTC = timezone.utc


@pytest.fixture
def window():
    return TimeWindow(
        start=datetime(2026, 11, 9, 0, 0, tzinfo=UTC),
        end=datetime(2026, 11, 10, 9, 0, tzinfo=UTC),
    )


def _git(repo: Path, *args: str, env: dict | None = None) -> None:
    full_env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", **(env or {})}
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=full_env)


def _commit(repo: Path, msg: str, email: str, when: str) -> None:
    f = repo / "f.txt"
    f.write_text(f.read_text() + msg + "\n" if f.exists() else msg + "\n")
    _git(repo, "add", ".")
    env = {
        "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when,
        "GIT_AUTHOR_EMAIL": email, "GIT_COMMITTER_EMAIL": email,
        "GIT_AUTHOR_NAME": "x", "GIT_COMMITTER_NAME": "x",
    }
    _git(repo, "commit", "-q", "-m", msg, env=env)


@pytest.fixture
def repo(tmp_path) -> Path:
    r = tmp_path / "code" / "svc"
    r.mkdir(parents=True)
    _git(r, "init", "-q", "-b", "main")
    _commit(r, "old work", "me@x.com", "2026-11-01T10:00:00+00:00")
    _commit(r, "teammate change", "other@x.com", "2026-11-09T11:00:00+00:00")
    _git(r, "checkout", "-q", "-b", "feat/OFF-12-retry")
    _commit(r, "OFF-12 add retry", "me@x.com", "2026-11-09T12:00:00+00:00")
    return r


from standup_generator.models import Comment, Commit, PullRequest, Ticket  # noqa: E402

T = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


def ticket(key, category="in_progress", **kw):
    kw.setdefault("summary", f"Summary {key}")
    kw.setdefault("status", "In Progress" if category == "in_progress" else "QA")
    kw.setdefault("url", f"https://co.atlassian.net/browse/{key}")
    kw.setdefault("source", "jira")
    return Ticket(key=key, category=category, **kw)


def commit(subject, branches=(), sha=None):
    return Commit(sha=sha or subject[:7], repo="svc", subject=subject, timestamp=T, branches=list(branches))


def pr(number, title, head="", state="open", created=T, approved=None):
    return PullRequest(number=number, title=title, repo="acme/svc", url=f"https://gh/{number}",
                       state=state, head_branch=head, created_at=created, updated_at=created,
                       approved=approved)


def comment(body, author="Alice"):
    return Comment(author=author, body=body, created_at=T)
