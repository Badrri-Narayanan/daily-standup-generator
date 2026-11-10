import httpx
import respx

from standup_generator.config import GitHubConfig
from standup_generator.sources.github import GitHubSource

API = "https://api.github.com"
ENV = {"GITHUB_TOKEN": "tok"}


def item(n, repo="acme/svc", state="open"):
    return {
        "number": n, "title": f"OFF-{n} change", "state": state,
        "html_url": f"https://github.com/{repo}/pull/{n}",
        "repository_url": f"{API}/repos/{repo}",
        "created_at": "2026-11-08T10:00:00Z", "updated_at": "2026-11-09T10:00:00Z",
        "pull_request": {"url": f"{API}/repos/{repo}/pulls/{n}"},
    }


def pull(n, state="open", draft=False, merged_at=None, ref=None):
    return {"number": n, "state": state, "draft": draft, "merged_at": merged_at,
            "head": {"ref": ref or f"feat/OFF-{n}"}}


def src(**kw):
    return GitHubSource(GitHubConfig(**kw), ENV)


def test_missing_token(window):
    with respx.mock(assert_all_called=False):
        r = GitHubSource(GitHubConfig(), {}).collect(window)
    assert r.errors == ["github: set GITHUB_TOKEN in .env"]


def test_maps_states(window):
    with respx.mock() as router:
        router.get(f"{API}/search/issues").respond(json={"items": [
            item(1), item(2), item(3, state="closed"), item(4, state="closed")]})
        router.get(f"{API}/repos/acme/svc/pulls/1").respond(json=pull(1))
        router.get(f"{API}/repos/acme/svc/pulls/2").respond(json=pull(2, draft=True))
        router.get(f"{API}/repos/acme/svc/pulls/3").respond(json=pull(3, "closed", merged_at="2026-11-09T12:00:00Z"))
        router.get(f"{API}/repos/acme/svc/pulls/4").respond(json=pull(4, "closed"))
        router.get(f"{API}/repos/acme/svc/pulls/1/reviews").respond(json=[])
        r = src().collect(window)
    assert r.errors == []
    assert {p.number: p.state for p in r.pull_requests} == {1: "open", 2: "draft", 3: "merged", 4: "closed"}
    pr1 = next(p for p in r.pull_requests if p.number == 1)
    assert pr1.repo == "acme/svc" and pr1.head_branch == "feat/OFF-1"
    assert pr1.url == "https://github.com/acme/svc/pull/1"


def test_open_pr_review_approved_flag(window):
    with respx.mock() as router:
        router.get(f"{API}/search/issues").respond(json={"items": [item(1)]})
        router.get(f"{API}/repos/acme/svc/pulls/1").respond(json=pull(1))
        router.get(f"{API}/repos/acme/svc/pulls/1/reviews").respond(
            json=[{"state": "COMMENTED"}, {"state": "APPROVED"}])
        r = src().collect(window)
    assert r.pull_requests[0].approved is True


def test_query_contains_author_and_date(window):
    with respx.mock() as router:
        route = router.get(f"{API}/search/issues").respond(json={"items": []})
        src(orgs=["acme"]).collect(window)
    q = route.calls[0].request.url.params["q"]
    assert "is:pr" in q and "author:@me" in q
    assert "updated:>=2026-11-09T00:00:00Z" in q
    assert "org:acme" in q


def test_per_pr_failure_keeps_pr_and_reports(window):
    with respx.mock() as router:
        router.get(f"{API}/search/issues").respond(json={"items": [item(1)]})
        router.get(f"{API}/repos/acme/svc/pulls/1").respond(500)
        r = src().collect(window)
    assert len(r.pull_requests) == 1 and r.pull_requests[0].head_branch == ""
    assert any("acme/svc#1" in e for e in r.errors)


def test_401(window):
    with respx.mock() as router:
        router.get(f"{API}/search/issues").respond(401)
        r = src().collect(window)
    assert r.errors == ["github: authentication failed — check GITHUB_TOKEN"]


def test_network_error(window):
    with respx.mock() as router:
        router.get(f"{API}/search/issues").mock(side_effect=httpx.ConnectError("down"))
        r = src().collect(window)
    assert r.errors[0].startswith("github: cannot reach")


def test_403_on_one_pr_keeps_others(window):
    with respx.mock() as router:
        router.get(f"{API}/search/issues").respond(json={"items": [item(1, repo="sso/locked"), item(2)]})
        router.get(f"{API}/repos/sso/locked/pulls/1").respond(403, headers={"X-GitHub-SSO": "required; url=x"})
        router.get(f"{API}/repos/acme/svc/pulls/2").respond(json=pull(2))
        router.get(f"{API}/repos/acme/svc/pulls/2/reviews").respond(json=[])
        r = src().collect(window)
    assert [p.number for p in r.pull_requests] == [1, 2]
    assert next(p for p in r.pull_requests if p.number == 2).head_branch == "feat/OFF-2"
    assert any("sso/locked#1" in e and "403" in e for e in r.errors)
