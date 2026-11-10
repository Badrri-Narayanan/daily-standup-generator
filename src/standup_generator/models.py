"""Normalized data shapes shared by sources, correlation, prompt and history."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

TicketCategory = Literal["in_progress", "completed", "other"]
PullRequestState = Literal["open", "draft", "merged", "closed"]


@dataclass
class TimeWindow:
    start: datetime
    end: datetime


@dataclass
class Comment:
    author: str
    body: str
    created_at: datetime


@dataclass
class Ticket:
    key: str
    summary: str
    status: str
    url: str
    category: TicketCategory
    source: str
    flagged: bool = False
    assignee_is_me: bool = False
    comments: list[Comment] = field(default_factory=list)


@dataclass
class Commit:
    sha: str
    repo: str
    subject: str
    timestamp: datetime
    branches: list[str] = field(default_factory=list)


@dataclass
class PullRequest:
    number: int
    title: str
    repo: str
    url: str
    state: PullRequestState
    head_branch: str
    created_at: datetime
    updated_at: datetime
    merged_at: datetime | None = None
    approved: bool | None = None


@dataclass
class SourceResult:
    source: str
    tickets: list[Ticket] = field(default_factory=list)
    commits: list[Commit] = field(default_factory=list)
    pull_requests: list[PullRequest] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)


@dataclass
class BlockerHint:
    ticket_key: str | None
    reason: str
    detail: str


@dataclass
class TicketActivity:
    ticket: Ticket
    commits: list[Commit] = field(default_factory=list)
    pull_requests: list[PullRequest] = field(default_factory=list)


@dataclass
class ActivityBundle:
    window: TimeWindow
    in_progress: list[TicketActivity] = field(default_factory=list)
    completed: list[TicketActivity] = field(default_factory=list)
    other_tickets: list[TicketActivity] = field(default_factory=list)
    other_commits: list[Commit] = field(default_factory=list)
    other_prs: list[PullRequest] = field(default_factory=list)
    blocker_hints: list[BlockerHint] = field(default_factory=list)
    source_errors: dict[str, list[str]] = field(default_factory=dict)
    source_info: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class GenerationResult:
    prompt: str
    bundle: ActivityBundle
    history_id: int | None = None
