from datetime import timedelta

from conftest import T, comment, pr, ticket

from standup_generator.blockers import find_blocker_hints
from standup_generator.config import BlockersConfig
from standup_generator.models import ActivityBundle, TicketActivity

CFG = BlockersConfig()


def bundle(window, **kw):
    return ActivityBundle(window=window, **kw)


def test_flagged_hint(window):
    b = bundle(window, in_progress=[TicketActivity(ticket("OFF-1", flagged=True))])
    hints = find_blocker_hints(b, CFG, T)
    assert [(h.ticket_key, h.reason) for h in hints] == [("OFF-1", "flagged in Jira")]


def test_keyword_hint_case_insensitive(window):
    t = ticket("OFF-1", comments=[comment("Waiting On infra to open the port"), comment("looks good")])
    hints = find_blocker_hints(bundle(window, in_progress=[TicketActivity(t)]), CFG, T)
    assert len(hints) == 1
    assert hints[0].reason == "comment mentions 'waiting on'"
    assert hints[0].detail.startswith("Alice: Waiting On infra")


def test_one_hint_per_comment(window):
    t = ticket("OFF-1", comments=[comment("blocked, waiting on infra, stuck")])
    assert len(find_blocker_hints(bundle(window, in_progress=[TicketActivity(t)]), CFG, T)) == 1


def test_completed_tickets_ignored(window):
    t = ticket("OFF-1", "completed", flagged=True)
    assert find_blocker_hints(bundle(window, completed=[TicketActivity(t)]), CFG, T) == []


def test_stale_pr_hint_only_after_threshold(window):
    old = pr(1, "OFF-1 x", created=T - timedelta(hours=25), approved=False)
    fresh = pr(2, "OFF-1 y", created=T - timedelta(hours=2), approved=False)
    b = bundle(window, in_progress=[TicketActivity(ticket("OFF-1"), pull_requests=[old, fresh])])
    hints = find_blocker_hints(b, CFG, T)
    assert [h.reason for h in hints] == ["PR open without approval for 25h"]
    assert hints[0].ticket_key == "OFF-1"


def test_approved_and_draft_pr_not_stale(window):
    approved = pr(1, "a", created=T - timedelta(hours=48), approved=True)
    draft = pr(2, "b", state="draft", created=T - timedelta(hours=48))
    assert find_blocker_hints(bundle(window, other_prs=[approved, draft]), CFG, T) == []


def test_other_pr_stale_has_no_ticket(window):
    old = pr(3, "misc", created=T - timedelta(hours=30))
    hints = find_blocker_hints(bundle(window, other_prs=[old]), CFG, T)
    assert hints[0].ticket_key is None
