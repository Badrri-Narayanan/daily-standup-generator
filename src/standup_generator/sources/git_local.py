"""Commits from local git repositories, filtered by author email."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from ..config import GitLocalConfig
from ..models import Commit, SourceResult, TimeWindow

MAX_COMMITS_PER_REPO = 200
SCAN_DEPTH = 2
_SEP = "\x1f"


def _global_git_email() -> str | None:
    try:
        out = subprocess.run(
            ["git", "config", "--global", "user.email"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def _strip_ref(ref: str) -> str:
    if ref.startswith("refs/heads/"):
        return ref[len("refs/heads/"):]
    if ref.startswith("refs/remotes/"):
        return ref[len("refs/remotes/"):].split("/", 1)[-1]
    return ref


def _find_repos(root: Path, depth: int) -> list[Path]:
    if not root.is_dir():
        return []
    if (root / ".git").exists():
        return [root]
    if depth == 0:
        return []
    found: list[Path] = []
    try:
        children = sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))
    except OSError:
        return []
    for child in children:
        found.extend(_find_repos(child, depth - 1))
    return found


class GitLocalSource:
    name = "git_local"

    def __init__(
        self,
        cfg: GitLocalConfig,
        default_email: Callable[[], str | None] = _global_git_email,
    ) -> None:
        self.cfg = cfg
        self._default_email = default_email

    def _repos(self) -> list[Path]:
        candidates: list[Path] = list(self.cfg.repos)
        for d in self.cfg.scan_dirs:
            candidates.extend(_find_repos(d, SCAN_DEPTH))
        seen: set[Path] = set()
        unique: list[Path] = []
        for p in candidates:
            key = p.resolve()
            if key not in seen:
                seen.add(key)
                unique.append(p)
        return unique

    def collect(self, window: TimeWindow) -> SourceResult:
        result = SourceResult(source=self.name)
        repos = self._repos()
        if not repos:
            result.info.append("git_local: no repos configured")
            return result
        emails = self.cfg.author_emails or [e for e in [self._default_email()] if e]
        if not emails:
            result.errors.append("git_local: no author email — set sources.git_local.author_emails")
            return result
        for repo in repos:
            self._collect_repo(repo, emails, window, result)
        return result

    def _collect_repo(self, repo: Path, emails: list[str], window: TimeWindow, result: SourceResult) -> None:
        if not repo.is_dir():
            result.errors.append(f"git_local: {repo}: directory does not exist")
            return
        cmd = [
            "git", "-C", str(repo), "log", "--all", "--source",
            f"--since={window.start.isoformat()}", f"--until={window.end.isoformat()}",
            *[f"--author={e}" for e in emails],
            f"--format=%H{_SEP}%aI{_SEP}%S{_SEP}%s", "-n", str(MAX_COMMITS_PER_REPO),
        ]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:
            result.errors.append(f"git_local: {repo}: {exc}")
            return
        if out.returncode != 0:
            reason = out.stderr.strip().splitlines()[0] if out.stderr.strip() else f"git exited {out.returncode}"
            result.errors.append(f"git_local: {repo}: {reason}")
            return
        by_sha: dict[str, Commit] = {}
        for line in out.stdout.splitlines():
            parts = line.split(_SEP, 3)
            if len(parts) != 4:
                continue
            sha, when, ref, subject = parts
            branch = _strip_ref(ref)
            if sha in by_sha:
                if branch and branch not in by_sha[sha].branches:
                    by_sha[sha].branches.append(branch)
                continue
            by_sha[sha] = Commit(
                sha=sha, repo=repo.name, subject=subject,
                timestamp=datetime.fromisoformat(when),
                branches=[branch] if branch else [],
            )
        result.commits.extend(by_sha.values())
