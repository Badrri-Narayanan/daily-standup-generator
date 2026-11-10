"""Jira Cloud tickets: in progress (assigned to me) and handed off by me in the window.

Read-only. The handoff window is sent as a relative range ending at Jira's now(),
so it doesn't depend on your Jira profile timezone.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import datetime
from typing import Any

import httpx

from ..config import JiraConfig
from ..models import Comment, SourceResult, Ticket, TimeWindow

MAX_TICKETS = 100
TIMEOUT = 15.0


class JiraError(Exception):
    pass


def adf_to_text(node: dict | str | None) -> str:
    """Flatten Atlassian Document Format into plain text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node.strip()
    parts: list[str] = []

    def walk(n: Any) -> None:
        if isinstance(n, dict):
            kind = n.get("type")
            if kind == "text":
                parts.append(n.get("text", ""))
            elif kind == "hardBreak":
                parts.append("\n")
            for child in n.get("content", []) or []:
                walk(child)
            if kind == "paragraph":
                parts.append("\n")
        elif isinstance(n, list):
            for child in n:
                walk(child)

    walk(node)
    return "".join(parts).strip()


def _quote_list(values: list[str]) -> str:
    return ", ".join('"' + v.replace('"', '\\"') + '"' for v in values)


def _parse_jira_time(value: str) -> datetime:
    # Jira: 2026-11-09T10:00:00.000+0000
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%f%z")


class JiraSource:
    name = "jira"

    def __init__(self, cfg: JiraConfig, env: Mapping[str, str], client: httpx.Client | None = None) -> None:
        self.cfg = cfg
        self.env = env
        self._client = client

    def collect(self, window: TimeWindow) -> SourceResult:
        result = SourceResult(source=self.name)
        if not self.cfg.base_url:
            result.errors.append("jira: set sources.jira.base_url")
            return result
        email, token = self.env.get(self.cfg.email_env), self.env.get(self.cfg.token_env)
        if not email or not token:
            result.errors.append(f"jira: set {self.cfg.email_env} / {self.cfg.token_env} in .env")
            return result
        base = self.cfg.base_url.rstrip("/")
        client = self._client or httpx.Client(timeout=TIMEOUT)
        try:
            self._collect(client, base, (email, token), window, result)
        except JiraError as exc:
            result.errors.append(str(exc))
        except httpx.HTTPError as exc:
            result.errors.append(f"jira: cannot reach {base}: {exc}")
        finally:
            if self._client is None:
                client.close()
        return result

    def _request(self, client: httpx.Client, method: str, url: str, auth, **kw) -> Any:
        resp = client.request(method, url, auth=auth, headers={"Accept": "application/json"}, **kw)
        if resp.status_code in (401, 403):
            raise JiraError(
                f"jira: authentication failed ({resp.status_code}) — "
                f"check {self.cfg.email_env} / {self.cfg.token_env}"
            )
        if resp.status_code == 400:
            try:
                msgs = resp.json().get("errorMessages") or []
            except ValueError:
                msgs = []
            raise JiraError(
                f"jira: query rejected — {'; '.join(msgs) or resp.text[:200]}. "
                "Check in_progress_statuses / handoff_statuses match your Jira workflow"
            )
        if resp.status_code >= 300:
            raise JiraError(f"jira: {method} {url} returned HTTP {resp.status_code}")
        return resp.json()

    def _collect(self, client, base, auth, window: TimeWindow, result: SourceResult) -> None:
        me = self._request(client, "GET", f"{base}/rest/api/3/myself", auth)["accountId"]
        fields = self._request(client, "GET", f"{base}/rest/api/3/field", auth)
        flagged_field = next((f["id"] for f in fields if f.get("name") == "Flagged"), None)
        wanted = ["summary", "status", "assignee", "comment"] + ([flagged_field] if flagged_field else [])

        project = f" AND project in ({', '.join(self.cfg.project_keys)})" if self.cfg.project_keys else ""
        in_progress = _quote_list(self.cfg.in_progress_statuses)
        # Relative range ("-Nm" .. now()) so Jira's profile timezone can't skew the window.
        minutes = math.ceil((window.end - window.start).total_seconds() / 60)
        during = f'DURING ("-{minutes}m", now())'
        changed = " OR ".join(
            f"status CHANGED TO {_quote_list([s])} BY currentUser() {during}"
            for s in self.cfg.handoff_statuses
        )
        jql_in_progress = f"assignee = currentUser() AND status in ({in_progress}){project}"
        jql_completed = f"({changed}) AND status not in ({in_progress}){project}"

        seen: set[str] = set()
        for jql, category in ((jql_in_progress, "in_progress"), (jql_completed, "completed")):
            for raw in self._search(client, base, auth, jql, wanted):
                key = raw["key"]
                if key in seen:
                    continue
                f = raw.get("fields", {})
                assignee_is_me = (f.get("assignee") or {}).get("accountId") == me
                if category == "completed" and assignee_is_me and self.cfg.exclude_if_reassigned_to_me:
                    continue
                seen.add(key)
                result.tickets.append(Ticket(
                    key=key,
                    summary=f.get("summary", ""),
                    status=(f.get("status") or {}).get("name", ""),
                    url=f"{base}/browse/{key}",
                    category=category,
                    source=self.name,
                    flagged=bool(f.get(flagged_field)) if flagged_field else False,
                    assignee_is_me=assignee_is_me,
                    comments=self._comments(f, window),
                ))

    def _search(self, client, base, auth, jql: str, fields: list[str]) -> list[dict]:
        issues: list[dict] = []
        token: str | None = None
        while len(issues) < MAX_TICKETS:
            body: dict[str, Any] = {"jql": jql, "fields": fields, "maxResults": MAX_TICKETS}
            if token:
                body["nextPageToken"] = token
            page = self._request(client, "POST", f"{base}/rest/api/3/search/jql", auth, json=body)
            issues.extend(page.get("issues", []))
            token = page.get("nextPageToken")
            if not token or page.get("isLast"):
                break
        return issues[:MAX_TICKETS]

    @staticmethod
    def _comments(fields: dict, window: TimeWindow) -> list[Comment]:
        out: list[Comment] = []
        for c in (fields.get("comment") or {}).get("comments", []):
            try:
                created = _parse_jira_time(c["created"])
            except (KeyError, ValueError):
                continue
            if created < window.start:
                continue
            out.append(Comment(
                author=(c.get("author") or {}).get("displayName", "unknown"),
                body=adf_to_text(c.get("body")),
                created_at=created,
            ))
        return out
