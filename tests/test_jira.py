import json

import httpx
import pytest
import respx

from standup_generator.config import JiraConfig
from standup_generator.sources.jira import JiraSource, adf_to_text

BASE = "https://co.atlassian.net"
ENV = {"JIRA_EMAIL": "me@co.com", "JIRA_API_TOKEN": "tok"}
ME = "acc-me"


def adf(text):
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


def issue(key, status, assignee=ME, comments=(), flagged=None):
    return {
        "key": key,
        "fields": {
            "summary": f"Summary {key}",
            "status": {"name": status},
            "assignee": {"accountId": assignee} if assignee else None,
            "comment": {"comments": [
                {"author": {"displayName": a}, "body": adf(b), "created": c} for a, b, c in comments
            ]},
            "customfield_100": flagged,
        },
    }


def mock_jira(router, in_progress, completed, captured=None):
    router.get(f"{BASE}/rest/api/3/myself").respond(json={"accountId": ME})
    router.get(f"{BASE}/rest/api/3/field").respond(
        json=[{"id": "customfield_100", "name": "Flagged"}, {"id": "summary", "name": "Summary"}]
    )

    def search(request):
        body = json.loads(request.content)
        if captured is not None:
            captured.append(body)
        issues = completed if "CHANGED TO" in body["jql"] else in_progress
        return httpx.Response(200, json={"issues": issues, "isLast": True})

    router.post(f"{BASE}/rest/api/3/search/jql").mock(side_effect=search)


def src(**kw):
    return JiraSource(JiraConfig(base_url=BASE, **kw), ENV)


IN_PROGRESS = [
    issue("OFF-1", "In Progress", flagged=[{"value": "Impediment"}], comments=[
        ("Alice", "Waiting on the platform team", "2026-11-09T10:00:00.000+0000"),
        ("Bob", "old comment", "2026-11-01T10:00:00.000+0000"),
    ]),
]
COMPLETED = [issue("OFF-2", "QA", assignee="acc-qa")]


def test_missing_token_reports_error_without_http(window):
    with respx.mock(assert_all_called=False):
        r = JiraSource(JiraConfig(base_url=BASE), {}).collect(window)
    assert r.errors == ["jira: set JIRA_EMAIL / JIRA_API_TOKEN in .env"]


def test_missing_base_url(window):
    r = JiraSource(JiraConfig(), ENV).collect(window)
    assert r.errors == ["jira: set sources.jira.base_url"]


def test_in_progress_and_completed(window):
    with respx.mock() as router:
        mock_jira(router, IN_PROGRESS, COMPLETED)
        r = src().collect(window)
    assert r.errors == []
    assert {t.key: t.category for t in r.tickets} == {"OFF-1": "in_progress", "OFF-2": "completed"}
    assert r.tickets[0].url == f"{BASE}/browse/OFF-1"


def test_completed_jql_uses_by_current_user(window):
    captured = []
    with respx.mock() as router:
        mock_jira(router, IN_PROGRESS, COMPLETED, captured)
        src(project_keys=["OFF"]).collect(window)
    completed_jql = next(b["jql"] for b in captured if "CHANGED TO" in b["jql"])
    assert "BY currentUser()" in completed_jql
    assert "assignee = currentUser()" not in completed_jql
    assert ('(status CHANGED TO "QA" BY currentUser() DURING ("-1980m", now()) OR '
            'status CHANGED TO "Ready for QA" BY currentUser() DURING ("-1980m", now())') in completed_jql
    assert "project in (OFF)" in completed_jql
    assert all("customfield_100" in b["fields"] for b in captured)


def test_bounced_back_ticket_excluded(window):
    bounced = [issue("OFF-3", "QA", assignee=ME)]
    with respx.mock() as router:
        mock_jira(router, [], bounced)
        r = src().collect(window)
    assert r.tickets == []


def test_bounced_back_kept_when_setting_off(window):
    bounced = [issue("OFF-3", "QA", assignee=ME)]
    with respx.mock() as router:
        mock_jira(router, [], bounced)
        r = src(exclude_if_reassigned_to_me=False).collect(window)
    assert [t.key for t in r.tickets] == ["OFF-3"]


def test_ticket_in_both_stays_in_progress(window):
    with respx.mock() as router:
        mock_jira(router, IN_PROGRESS, [issue("OFF-1", "In Progress", assignee="x")])
        r = src().collect(window)
    assert [(t.key, t.category) for t in r.tickets] == [("OFF-1", "in_progress")]


def test_comments_filtered_to_window_and_plaintext(window):
    with respx.mock() as router:
        mock_jira(router, IN_PROGRESS, [])
        r = src().collect(window)
    t = r.tickets[0]
    assert [(c.author, c.body) for c in t.comments] == [("Alice", "Waiting on the platform team")]


def test_flagged(window):
    with respx.mock() as router:
        mock_jira(router, IN_PROGRESS, COMPLETED)
        r = src().collect(window)
    flags = {t.key: t.flagged for t in r.tickets}
    assert flags == {"OFF-1": True, "OFF-2": False}


def test_400_bad_status_is_readable_error(window):
    with respx.mock() as router:
        router.get(f"{BASE}/rest/api/3/myself").respond(json={"accountId": ME})
        router.get(f"{BASE}/rest/api/3/field").respond(json=[])
        router.post(f"{BASE}/rest/api/3/search/jql").respond(
            400, json={"errorMessages": ["The value 'In QA' does not exist for the field 'status'."]}
        )
        r = src().collect(window)
    assert len(r.errors) == 1
    assert "does not exist" in r.errors[0] and "handoff_statuses" in r.errors[0]


def test_401(window):
    with respx.mock() as router:
        router.get(f"{BASE}/rest/api/3/myself").respond(401)
        r = src().collect(window)
    assert r.errors == ["jira: authentication failed (401) — check JIRA_EMAIL / JIRA_API_TOKEN"]


def test_network_error(window):
    with respx.mock() as router:
        router.get(f"{BASE}/rest/api/3/myself").mock(side_effect=httpx.ConnectError("boom"))
        r = src().collect(window)
    assert r.errors[0].startswith(f"jira: cannot reach {BASE}")


def test_pagination_follows_next_page_token(window):
    pages = iter([
        {"issues": [issue("OFF-1", "In Progress")], "nextPageToken": "p2"},
        {"issues": [issue("OFF-4", "In Progress")], "isLast": True},
        {"issues": [], "isLast": True},
    ])
    with respx.mock() as router:
        router.get(f"{BASE}/rest/api/3/myself").respond(json={"accountId": ME})
        router.get(f"{BASE}/rest/api/3/field").respond(json=[])
        router.post(f"{BASE}/rest/api/3/search/jql").mock(side_effect=lambda req: httpx.Response(200, json=next(pages)))
        r = src().collect(window)
    assert [t.key for t in r.tickets] == ["OFF-1", "OFF-4"]


def test_adf_to_text():
    doc = {"type": "doc", "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]},
        {"type": "paragraph", "content": [{"type": "text", "text": "c"}]},
    ]}
    assert adf_to_text(doc) == "ab\nc"
    assert adf_to_text("plain") == "plain"
    assert adf_to_text(None) == ""
