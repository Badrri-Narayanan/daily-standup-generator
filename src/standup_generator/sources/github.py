"""GitHub pull requests authored by me and updated in the window. Read-only."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

import httpx

from ..config import GitHubConfig
from ..models import PullRequest, SourceResult, TimeWindow

MAX_PRS = 50
TIMEOUT = 15.0


class GitHubAuthError(Exception):
    def __init__(self, status: int, hint: str = "") -> None:
        super().__init__(f"HTTP {status}{f' ({hint})' if hint else ''}")
        self.status = status


def _ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


class GitHubSource:
    name = "github"

    def __init__(self, cfg: GitHubConfig, env: Mapping[str, str], client: httpx.Client | None = None) -> None:
        self.cfg = cfg
        self.env = env
        self._client = client

    def collect(self, window: TimeWindow) -> SourceResult:
        result = SourceResult(source=self.name)
        token = self.env.get(self.cfg.token_env)
        if not token:
            result.errors.append(f"github: set {self.cfg.token_env} in .env")
            return result
        api = self.cfg.api_url.rstrip("/")
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        client = self._client or httpx.Client(timeout=TIMEOUT)
        try:
            self._collect(client, api, headers, window, result)
        except GitHubAuthError:
            result.errors.append(f"github: authentication failed — check {self.cfg.token_env}")
        except httpx.HTTPStatusError as exc:
            result.errors.append(f"github: search failed with HTTP {exc.response.status_code}")
        except httpx.HTTPError as exc:
            result.errors.append(f"github: cannot reach {api}: {exc}")
        finally:
            if self._client is None:
                client.close()
        return result

    def _get(self, client: httpx.Client, url: str, headers: dict, **kw) -> Any:
        resp = client.get(url, headers=headers, **kw)
        if resp.status_code in (401, 403):
            hint = resp.headers.get("X-GitHub-SSO") or (
                "rate limited" if resp.headers.get("X-RateLimit-Remaining") == "0" else "")
            raise GitHubAuthError(resp.status_code, hint)
        resp.raise_for_status()
        return resp.json()

    def _collect(self, client, api: str, headers: dict, window: TimeWindow, result: SourceResult) -> None:
        since = window.start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        q = " ".join(["is:pr", "author:@me", f"updated:>={since}", *[f"org:{o}" for o in self.cfg.orgs]])
        data = self._get(client, f"{api}/search/issues", headers, params={"q": q, "per_page": MAX_PRS})
        for it in data.get("items", [])[:MAX_PRS]:
            repo = it["repository_url"].split("/repos/", 1)[-1]
            pr = PullRequest(
                number=it["number"],
                title=it.get("title", ""),
                repo=repo,
                url=it.get("html_url", ""),
                state="closed" if it.get("state") == "closed" else "open",
                head_branch="",
                created_at=_ts(it["created_at"]),
                updated_at=_ts(it["updated_at"]),
            )
            try:
                self._enrich(client, api, headers, pr)
            except (GitHubAuthError, httpx.HTTPError) as exc:
                result.errors.append(f"github: could not load details for {repo}#{pr.number}: {exc}")
            result.pull_requests.append(pr)

    def _enrich(self, client, api: str, headers: dict, pr: PullRequest) -> None:
        detail = self._get(client, f"{api}/repos/{pr.repo}/pulls/{pr.number}", headers)
        pr.head_branch = (detail.get("head") or {}).get("ref", "")
        pr.merged_at = _ts(detail.get("merged_at"))
        if pr.merged_at:
            pr.state = "merged"
        elif detail.get("state") == "closed":
            pr.state = "closed"
        elif detail.get("draft"):
            pr.state = "draft"
        else:
            pr.state = "open"
        if pr.state == "open":
            reviews = self._get(client, f"{api}/repos/{pr.repo}/pulls/{pr.number}/reviews", headers)
            pr.approved = any(r.get("state") == "APPROVED" for r in reviews)
