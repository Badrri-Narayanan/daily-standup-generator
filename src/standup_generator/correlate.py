"""Group commits and PRs under the tickets they mention."""

from __future__ import annotations

import re

from .models import ActivityBundle, Commit, PullRequest, SourceResult, Ticket, TicketActivity, TimeWindow

NOT_FOUND_STATUS = "not found in any ticket source"
_RANK = {"in_progress": 0, "completed": 1, "other": 2}


def _prefix(key: str) -> str:
    return key.rsplit("-", 1)[0]


def _compile(key_pattern: str, flags: int = 0) -> re.Pattern:
    # Keys must stand alone: "XOFF-1" and "OFF-1x" are not OFF-1.
    return re.compile(rf"(?<![A-Za-z0-9])(?:{key_pattern})(?![A-Za-z0-9])", flags)


def _keys(regex: re.Pattern, texts: list[str], known: set[str]) -> list[str]:
    found: list[str] = []
    for text in texts:
        for m in regex.finditer(text or ""):
            key = m.group(0).upper()
            if _prefix(key) in known and key not in found:
                found.append(key)
    return found


def correlate(
    window: TimeWindow,
    results: list[SourceResult],
    key_pattern: str,
    known_prefixes: list[str] | None = None,
) -> ActivityBundle:
    """Attach commits/PRs to tickets.

    Only keys whose project prefix is known (configured, or seen on a real ticket) count,
    so words like "utf-8" or "node-18" never become tickets. Branch names match
    case-insensitively; commit subjects and PR titles must be upper-case.
    """
    branch_re = _compile(key_pattern, re.IGNORECASE)
    text_re = _compile(key_pattern)
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
    known = {p.upper() for p in (known_prefixes or [])} | {_prefix(k) for k in tickets}

    def keys_for(branches: list[str], texts: list[str]) -> list[str]:
        out = _keys(branch_re, branches, known)
        out += [k for k in _keys(text_re, texts, known) if k not in out]
        return out

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
            targets = attach(keys_for(c.branches, [c.subject]))
            if not targets:
                bundle.other_commits.append(c)
            for ta in targets:
                ta.commits.append(c)
        for p in r.pull_requests:
            targets = attach(keys_for([p.head_branch], [p.title]))
            if not targets:
                bundle.other_prs.append(p)
            for ta in targets:
                ta.pull_requests.append(p)

    for ta in activity.values():
        {"in_progress": bundle.in_progress, "completed": bundle.completed,
         "other": bundle.other_tickets}[ta.ticket.category].append(ta)
    return bundle
