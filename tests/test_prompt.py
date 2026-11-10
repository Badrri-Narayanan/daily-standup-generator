from datetime import date

from conftest import comment, commit, pr, ticket

from standup_generator.config import PromptConfig
from standup_generator.models import ActivityBundle, BlockerHint, TicketActivity
from standup_generator.prompt import build_prompt

TODAY = date(2026, 11, 10)
HEADINGS = ["## Instructions", "## Context", "## In progress", "## Completed / moved to QA",
            "## Other activity", "## Blockers", "## Data notes"]


def full_bundle(window, **kw):
    base = dict(
        in_progress=[TicketActivity(ticket("OFF-1", comments=[comment("Waiting on infra")]),
                                    commits=[commit("OFF-1 add retry")], pull_requests=[pr(7, "OFF-1 retry")])],
        completed=[TicketActivity(ticket("OFF-2", "completed"))],
        other_commits=[commit("tidy readme")],
        blocker_hints=[BlockerHint("OFF-1", "comment mentions 'waiting on'", "Alice: Waiting on infra")],
        source_errors={"github": ["github: set GITHUB_TOKEN in .env"]},
    )
    base.update(kw)
    return ActivityBundle(window=window, **base)


def render(window, plans="", blockers="", cfg=None, **kw):
    return build_prompt(full_bundle(window, **kw), plans, blockers, cfg or PromptConfig(), TODAY)


def test_section_order(window):
    out = render(window)
    positions = [out.index(h) for h in HEADINGS]
    assert positions == sorted(positions)


def test_contains_no_invent_instruction_and_order(window):
    out = render(window)
    assert "Use only the facts provided below. Never invent work, tickets, or plans." in out
    assert "In progress → Completed / moved to QA → Blockers" in out


def test_ticket_details_rendered(window):
    out = render(window)
    for s in ["OFF-1", "Summary OFF-1", "OFF-1 add retry", "#7", "Waiting on infra", "OFF-2", "tidy readme"]:
        assert s in out
    assert "2026-11-09" in out


def test_user_blockers_before_hints(window):
    out = render(window, blockers="Need prod DB access")
    assert out.index("Reported by me:") < out.index("Need prod DB access") < out.index("Possible blockers — verify:")


def test_no_blockers_renders_none_reported(window):
    out = render(window, blocker_hints=[])
    blockers_section = out.split("## Blockers")[1]
    assert "None reported." in blockers_section


def test_comment_truncated(window):
    long = "x" * 600
    out = render(window, cfg=PromptConfig(max_comment_chars=500),
                 in_progress=[TicketActivity(ticket("OFF-1", comments=[comment(long)]))])
    assert ("x" * 499 + "…") in out and ("x" * 500) not in out


def test_source_error_note(window):
    out = render(window)
    assert ("- github was unavailable: github: set GITHUB_TOKEN in .env. "
            "Missing data from this source does not mean no work was done.") in out


def test_no_data_notes_when_no_errors(window):
    assert "## Data notes" not in render(window, source_errors={})


def test_plans_included_only_when_given(window):
    assert "My plans for today:" not in render(window)
    out = render(window, plans="Finish OFF-1 tests")
    assert "My plans for today:" in out and "Finish OFF-1 tests" in out


def test_empty_groups_render_none(window):
    out = render(window, in_progress=[], completed=[], other_commits=[], blocker_hints=[])
    assert out.split("## In progress")[1].split("##")[0].strip() == "None."


def test_custom_template_path(window, tmp_path):
    t = tmp_path / "t.j2"
    t.write_text("CUSTOM {{ today }} {{ bundle.in_progress|length }} {{ 'abcdef'|truncate_chars(4) }}")
    out = render(window, cfg=PromptConfig(template_path=t))
    assert out == "CUSTOM 2026-11-10 1 abc…"


def test_pr_dates_rendered(window):
    from datetime import datetime, timezone
    p = pr(9, "OFF-1 old", state="merged")
    p.merged_at = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)
    out = render(window, in_progress=[TicketActivity(ticket("OFF-1"), pull_requests=[p])])
    assert "merged 2026-10-20" in out and "opened 2026-11-09" in out
