"""Heuristic 'possible blocker' hints. Never authoritative."""

from __future__ import annotations

from datetime import datetime

from .config import BlockersConfig
from .models import ActivityBundle, BlockerHint, PullRequest

DETAIL_CHARS = 200


def _stale_pr_hint(p: PullRequest, ticket_key: str | None, cfg: BlockersConfig, now: datetime) -> BlockerHint | None:
    if p.state != "open" or p.approved is True:
        return None
    hours = int((now - p.created_at).total_seconds() // 3600)
    if hours < cfg.stale_pr_hours:
        return None
    return BlockerHint(ticket_key, f"PR open without approval for {hours}h", f"{p.repo}#{p.number} {p.title}")


def find_blocker_hints(bundle: ActivityBundle, cfg: BlockersConfig, now: datetime) -> list[BlockerHint]:
    hints: list[BlockerHint] = []
    keywords = [k.lower() for k in cfg.keywords]
    seen_prs: set[tuple[str, int]] = set()

    for ta in bundle.in_progress + bundle.other_tickets:
        t = ta.ticket
        if t.flagged:
            hints.append(BlockerHint(t.key, "flagged in Jira", t.summary))
        for c in t.comments:
            body = c.body.lower()
            hit = next((k for k in keywords if k in body), None)
            if hit:
                hints.append(BlockerHint(t.key, f"comment mentions '{hit}'", f"{c.author}: {c.body}"[:DETAIL_CHARS]))
        for p in ta.pull_requests:
            if (p.repo, p.number) in seen_prs:
                continue
            seen_prs.add((p.repo, p.number))
            if h := _stale_pr_hint(p, t.key, cfg, now):
                hints.append(h)

    for p in bundle.other_prs:
        if (p.repo, p.number) not in seen_prs and (h := _stale_pr_hint(p, None, cfg, now)):
            hints.append(h)
    return hints
