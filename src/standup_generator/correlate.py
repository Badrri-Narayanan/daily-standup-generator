"""Group commits and PRs under the tickets they mention."""

from __future__ import annotations

import re

from .models import ActivityBundle, Commit, PullRequest, SourceResult, Ticket, TicketActivity, TimeWindow

NOT_FOUND_STATUS = "not found in any ticket source"
_RANK = {"in_progress": 0, "completed": 1, "other": 2}


def _keys(regex: re.Pattern, *texts: str) -> list[str]:
    found: list[str] = []
    for text in texts:
        for m in regex.findall(text or ""):
            key = m.upper()
            if key not in found:
                found.append(key)
    return found


def correlate(window: TimeWindow, results: list[SourceResult], key_pattern: str) -> ActivityBundle:
    regex = re.compile(key_pattern, re.IGNORECASE)
    bundle = ActivityBundle(window=window)
    tickets: dict[str, Ticket] = {}

    for r in results:
        if r.errors:
            bundle.source_errors.setdefault(r.source, []).extend(r.errors)
        if r.info:
            bundle.source_info.setdefault(r.source, []).extend(r.info)
        for t in r.tickets:
            key = t.key.upper()
            existing = tickets.get(key)
            if existing is None or _RANK[t.category] < _RANK[existing.category]:
                tickets[key] = t

    activity = {key: TicketActivity(ticket=t) for key, t in tickets.items()}

    def attach(keys: list[str]) -> list[TicketActivity]:
        targets = []
        for key in keys:
            if key not in activity:
                activity[key] = TicketActivity(ticket=Ticket(
                    key=key, summary="", status=NOT_FOUND_STATUS, url="",
                    category="other", source="correlate",
                ))
            targets.append(activity[key])
        return targets

    for r in results:
        for c in r.commits:
            targets = attach(_keys(regex, *c.branches, c.subject))
            if not targets:
                bundle.other_commits.append(c)
            for ta in targets:
                ta.commits.append(c)
        for p in r.pull_requests:
            targets = attach(_keys(regex, p.head_branch, p.title))
            if not targets:
                bundle.other_prs.append(p)
            for ta in targets:
                ta.pull_requests.append(p)

    for ta in activity.values():
        {"in_progress": bundle.in_progress, "completed": bundle.completed,
         "other": bundle.other_tickets}[ta.ticket.category].append(ta)
    return bundle
