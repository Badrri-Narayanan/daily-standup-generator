from conftest import commit, pr, ticket

from standup_generator.correlate import correlate
from standup_generator.models import SourceResult

PATTERN = r"[A-Z][A-Z0-9]+-\d+"


def test_lowercase_branch_key_normalized(window):
    c = commit("fix stuff", ["feat/off-1234-retry"])
    b = correlate(window, [SourceResult("git_local", commits=[c]),
                           SourceResult("jira", tickets=[ticket("OFF-1234")])], PATTERN)
    assert b.in_progress[0].commits == [c]
    assert b.other_commits == []


def test_pr_attached_by_title_and_branch(window):
    p1, p2 = pr(1, "OFF-1 retry"), pr(2, "misc", head="bugfix/OFF-2-x")
    b = correlate(window, [SourceResult("github", pull_requests=[p1, p2]),
                           SourceResult("jira", tickets=[ticket("OFF-1"), ticket("OFF-2", "completed")])], PATTERN)
    assert b.in_progress[0].pull_requests == [p1]
    assert b.completed[0].pull_requests == [p2]


def test_unmatched_commit_and_pr_go_to_other(window):
    c, p = commit("tidy readme"), pr(3, "docs")
    b = correlate(window, [SourceResult("git_local", commits=[c]), SourceResult("github", pull_requests=[p])], PATTERN)
    assert b.other_commits == [c] and b.other_prs == [p]


def test_key_without_ticket_becomes_other_ticket(window):
    c = commit("OFF-99 spike")
    b = correlate(window, [SourceResult("git_local", commits=[c])], PATTERN)
    assert len(b.other_tickets) == 1
    other = b.other_tickets[0]
    assert other.ticket.key == "OFF-99"
    assert other.ticket.status == "not found in any ticket source"
    assert other.commits == [c]


def test_commit_mentioning_two_keys_attaches_to_both(window):
    c = commit("OFF-1 OFF-2 shared fix")
    b = correlate(window, [SourceResult("git_local", commits=[c]),
                           SourceResult("jira", tickets=[ticket("OFF-1"), ticket("OFF-2")])], PATTERN)
    assert all(ta.commits == [c] for ta in b.in_progress)


def test_in_progress_wins_over_completed_duplicate(window):
    b = correlate(window, [SourceResult("a", tickets=[ticket("OFF-1", "completed")]),
                           SourceResult("b", tickets=[ticket("OFF-1", "in_progress")])], PATTERN)
    assert [t.ticket.key for t in b.in_progress] == ["OFF-1"] and b.completed == []


def test_other_category_ticket_goes_to_other(window):
    b = correlate(window, [SourceResult("x", tickets=[ticket("LIN-5", "other")])], PATTERN)
    assert b.other_tickets[0].ticket.key == "LIN-5"


def test_source_errors_and_info_collected(window):
    b = correlate(window, [SourceResult("jira", errors=["jira: bad"]), SourceResult("git_local", info=["none"])], PATTERN)
    assert b.source_errors == {"jira": ["jira: bad"]}
    assert b.source_info == {"git_local": ["none"]}
