# Daily Standup Generator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local, single-user Python web app + library that collects Jira tickets, GitHub PRs and local git commits for the last working day, and builds a copy-paste LLM prompt for a Yesterday/Today/Blockers standup, with a SQLite history outside the repo.

**Architecture:** Pluggable `Source` adapters each return a normalized `SourceResult`; `correlate` groups commits/PRs under tickets; `blockers` adds hints; `prompt` renders a Jinja2 template; `generator.generate()` orchestrates and optionally saves to `HistoryStore`. FastAPI serves one plain HTML/JS page; argparse CLI wraps the same API.

**Tech Stack:** Python 3.12 (via `uv`), FastAPI, uvicorn, httpx, pydantic v2, Jinja2, PyYAML, python-dotenv, stdlib sqlite3; pytest, respx.

**Spec:** `docs/design.md`

## Global Constraints

- Python `>=3.11`; system python is 3.9, so create the env with `uv venv --python 3.12 && uv pip install -e ".[dev]"`. All commands below run inside `.venv` (`source .venv/bin/activate`).
- Package name `standup_generator`, src layout: `src/standup_generator/`. Console script `standup`.
- Strictly read-only against Jira and GitHub. No LLM calls anywhere.
- Secrets only from environment / `.env`; never rendered into the prompt, history, or API responses.
- History DB default `~/.local/share/standup-generator/history.db`; never inside the repo. `.gitignore` already ignores `.env`, `*.db`, `*.sqlite*`.
- Server binds `127.0.0.1` by default, port `8765`.
- Every source failure is caught and reported as a human-readable string in `SourceResult.errors`; never a traceback to the user, never silently empty.
- HTTP timeout 15s. Caps: 100 tickets, 200 commits per repo, 50 PRs.
- Default config values exactly as in `docs/design.md` §7 (statuses: in progress `["In Progress", "In Review", "Code Review"]`, handoff `["QA", "Ready for QA", "In QA", "Done"]`; blocker keywords `[blocked, blocker, "waiting on", "waiting for", "depends on", stuck]`; `stale_pr_hours: 24`; `max_comment_chars: 500`; ticket key pattern `[A-Z][A-Z0-9]+-\d+`).
- Commits: `feat:`/`chore:`/`test:` prefix; if the user provides a Jira key, include it (`feat: OFF-1234 ...`). Every commit ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Status name not in the user's Jira workflow** → Jira returns 400 for the JQL; expect a `SourceResult.errors` entry naming the bad status list, other sources still run. (Task 4)
2. **Missing token/env var for an enabled source** → expect error `"<source>: set JIRA_API_TOKEN in .env"`-style message, no exception. (Tasks 4, 5)
3. **Configured repo path missing or not a git repo** → that repo yields an error line, other repos still produce commits. (Task 3)
4. **Lowercase ticket keys in branch names** (`feat/off-1234-retry`) → matched case-insensitively and normalized to `OFF-1234`. (Task 6)
5. **Very long comments / Jira ADF rich text** → comments converted to plain text and truncated to `max_comment_chars` with `…`. (Tasks 4, 7)

---

## File Structure

```
pyproject.toml
standup.example.yaml
.env.example
README.md
src/standup_generator/
  __init__.py          # exports load_config, generate, AppConfig, GenerationResult
  models.py            # dataclasses
  config.py            # pydantic config + load_config
  window.py            # last working day window
  sources/__init__.py
  sources/base.py      # Source protocol
  sources/git_local.py
  sources/jira.py
  sources/github.py
  sources/registry.py  # build_sources
  correlate.py
  blockers.py
  prompt.py
  templates/prompt.md.j2
  history.py
  generator.py
  cli.py
  web/app.py
  web/static/index.html, app.js, style.css
tests/  (one test file per module, plus tests/conftest.py)
```

---

### Task 1: Project scaffold, models, config

**Files:**
- Create: `pyproject.toml`, `src/standup_generator/__init__.py`, `src/standup_generator/models.py`, `src/standup_generator/config.py`, `standup.example.yaml`, `.env.example`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces (`models.py`, all `@dataclass`, datetimes tz-aware):
  - `TimeWindow(start: datetime, end: datetime)`
  - `Comment(author: str, body: str, created_at: datetime)`
  - `Ticket(key: str, summary: str, status: str, url: str, category: Literal["in_progress","completed","other"], source: str, flagged: bool = False, assignee_is_me: bool = False, comments: list[Comment] = [])` (use `field(default_factory=list)`)
  - `Commit(sha: str, repo: str, subject: str, timestamp: datetime, branches: list[str])`
  - `PullRequest(number: int, title: str, repo: str, url: str, state: Literal["open","draft","merged","closed"], head_branch: str, created_at: datetime, updated_at: datetime, merged_at: datetime | None = None, approved: bool | None = None)`
  - `SourceResult(source: str, tickets: list[Ticket]=[], commits: list[Commit]=[], pull_requests: list[PullRequest]=[], errors: list[str]=[], info: list[str]=[])`
  - `BlockerHint(ticket_key: str | None, reason: str, detail: str)`
  - `TicketActivity(ticket: Ticket, commits: list[Commit], pull_requests: list[PullRequest])`
  - `ActivityBundle(window: TimeWindow, in_progress: list[TicketActivity], completed: list[TicketActivity], other_tickets: list[TicketActivity], other_commits: list[Commit], other_prs: list[PullRequest], blocker_hints: list[BlockerHint], source_errors: dict[str, list[str]], source_info: dict[str, list[str]])`
  - `GenerationResult(prompt: str, bundle: ActivityBundle, history_id: int | None)`
- Produces (`config.py`, pydantic `BaseModel`s mirroring design §7): `JiraConfig`, `GitHubConfig`, `GitLocalConfig`, `CustomSourceConfig(path: str, options: dict = {})`, `SourcesConfig(jira, github, git_local, custom: list[CustomSourceConfig])`, `BlockersConfig`, `HistoryConfig(enabled: bool = True, db_path: Path)`, `PromptConfig(template_path: Path | None, max_comment_chars: int = 500)`, `AppConfig(timezone: str | None, working_days: list[str], holidays: list[date], ticket_key_pattern: str, sources, blockers, history, prompt)`. `JiraConfig.base_url` optional; `enabled` defaults: jira/github `True`, git_local `True`.
- `load_config(path: str | Path | None = None) -> AppConfig`: lookup `path` → `./standup.yaml` → `~/.config/standup/standup.yaml` → all defaults. Calls `dotenv.load_dotenv()` for `./.env` and the config file's directory `.env`. Expands `~` in `db_path`, `repos`, `scan_dirs`, `template_path`.

- [ ] **Step 1: Create `pyproject.toml`** (hatchling, src layout, deps listed in Tech Stack, `[project.optional-dependencies] dev = ["pytest", "respx"]`, `[project.scripts] standup = "standup_generator.cli:main"`, package data includes `templates/*` and `web/static/*`). Run `uv venv --python 3.12 && source .venv/bin/activate && uv pip install -e ".[dev]"`. Expected: install succeeds.

- [ ] **Step 2: Write failing tests** in `tests/test_config.py`:

```python
def test_defaults_when_no_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path); monkeypatch.setenv("HOME", str(tmp_path))
    cfg = load_config()
    assert cfg.working_days == ["mon", "tue", "wed", "thu", "fri"]
    assert cfg.sources.jira.in_progress_statuses == ["In Progress", "In Review", "Code Review"]
    assert cfg.sources.jira.handoff_statuses == ["QA", "Ready for QA", "In QA", "Done"]
    assert cfg.sources.jira.exclude_if_reassigned_to_me is True
    assert cfg.blockers.stale_pr_hours == 24
    assert cfg.prompt.max_comment_chars == 500
    assert cfg.history.db_path == tmp_path / ".local/share/standup-generator/history.db"

def test_explicit_file_overrides(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text("sources:\n  jira:\n    handoff_statuses: [QA]\n  git_local:\n    repos: ['~/x']\n")
    cfg = load_config(p)
    assert cfg.sources.jira.handoff_statuses == ["QA"]
    assert cfg.sources.git_local.repos == [Path.home() / "x"]

def test_invalid_working_day_rejected(tmp_path):
    p = tmp_path / "s.yaml"; p.write_text("working_days: [funday]\n")
    with pytest.raises(ValueError):
        load_config(p)

def test_example_config_loads():
    assert load_config(Path(__file__).parent.parent / "standup.example.yaml")
```

- [ ] **Step 3: Run** `pytest tests/test_config.py -v`. Expected: FAIL (ImportError).
- [ ] **Step 4: Implement** `models.py`, `config.py`, `standup.example.yaml` (design §7 verbatim, with comments), `.env.example` (`JIRA_EMAIL=`, `JIRA_API_TOKEN=`, `GITHUB_TOKEN=`). `working_days` validated against `mon..sun`.
- [ ] **Step 5: Run** `pytest -v`. Expected: PASS.
- [ ] **Step 6: Commit** `chore: scaffold package with config and models`.

---

### Task 2: Last-working-day window

**Files:**
- Create: `src/standup_generator/window.py`
- Test: `tests/test_window.py`

**Interfaces:**
- Consumes: `TimeWindow`.
- Produces: `compute_window(now: datetime, working_days: list[str], holidays: list[date], since: date | None = None) -> TimeWindow`. `now` is tz-aware; `start` is 00:00 in `now`'s tz of the previous working day (walk back from yesterday, skipping non-working days and holidays); `since` overrides start date. `end == now`. Also `resolve_tz(name: str | None) -> tzinfo` (zoneinfo, or system local).

- [ ] **Step 1: Write failing tests:**

```python
TZ = ZoneInfo("Europe/London"); WD = ["mon","tue","wed","thu","fri"]
def test_tuesday_goes_to_monday():
    w = compute_window(datetime(2026,11,10,9,0,tzinfo=TZ), WD, [])
    assert w.start == datetime(2026,11,9,0,0,tzinfo=TZ)
def test_monday_goes_to_friday():
    assert compute_window(datetime(2026,11,9,9,tzinfo=TZ), WD, []).start.date() == date(2026,11,6)
def test_skips_holiday():
    assert compute_window(datetime(2026,11,10,9,tzinfo=TZ), WD, [date(2026,11,9)]).start.date() == date(2026,11,6)
def test_since_override():
    assert compute_window(datetime(2026,11,10,9,tzinfo=TZ), WD, [], since=date(2026,11,1)).start.date() == date(2026,11,1)
def test_end_is_now():
    now = datetime(2026,11,10,9,tzinfo=TZ); assert compute_window(now, WD, []).end == now
```

- [ ] **Step 2: Run** `pytest tests/test_window.py -v` → FAIL.
- [ ] **Step 3: Implement.** Guard: walk back at most 31 days, then raise `ValueError("no working day found in last 31 days")`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: compute last working day window`.

---

### Task 3: Source protocol + local git source

**Files:**
- Create: `src/standup_generator/sources/__init__.py`, `sources/base.py`, `sources/git_local.py`
- Test: `tests/test_git_local.py`

**Interfaces:**
- Produces (`base.py`): `class Source(Protocol): name: str; def collect(self, window: TimeWindow) -> SourceResult: ...`
- Produces: `GitLocalSource(cfg: GitLocalConfig, run: Callable = subprocess.run)` with `name = "git_local"`.
  - Repo discovery: each `repos` entry, plus directories under each `scan_dirs` entry up to depth 2 that contain `.git`. De-duplicate by resolved path.
  - Author emails: `cfg.author_emails` or `git config --global user.email`; if neither, error `"git_local: no author email — set sources.git_local.author_emails"`.
  - Per repo: `git -C <repo> log --all --source --since=<start ISO> --until=<end ISO> --author=<e1> --author=<e2> --format=%H%x1f%aI%x1f%S%x1f%s -n 200`. `%S` → `branches=[ref with refs/heads/ or refs/remotes/<x>/ stripped]`. Duplicate SHAs collapse (union branches). `repo` = directory name.
  - Missing path / non-zero exit → `errors.append(f"git_local: {path}: <reason>")`, continue.
  - No repos configured → `info.append("git_local: no repos configured")`, no error.

- [ ] **Step 1: Write failing tests** using a real temp repo (fixture runs `git init`, sets `user.email me@x.com`, makes commits with `GIT_AUTHOR_DATE`/`GIT_COMMITTER_DATE` env, one by `other@x.com`, one on branch `feat/OFF-12-retry`):

```python
def test_collects_only_my_commits_in_window(repo, window): ...
    # assert subjects == {"OFF-12 add retry"} and other author's commit absent, old commit absent
def test_branch_from_source(repo, window):
    # assert "feat/OFF-12-retry" in commit.branches
def test_missing_repo_reports_error_and_continues(repo, window, tmp_path):
    src = GitLocalSource(GitLocalConfig(repos=[tmp_path/"nope", repo], author_emails=["me@x.com"]))
    r = src.collect(window)
    assert len(r.commits) >= 1 and any("nope" in e for e in r.errors)
def test_scan_dirs_finds_nested_repo(repo, window): ...
def test_no_repos_is_info_not_error(window):
    r = GitLocalSource(GitLocalConfig(repos=[], scan_dirs=[], author_emails=["a@b"])).collect(window)
    assert r.errors == [] and r.info
```

- [ ] **Step 2: Run** `pytest tests/test_git_local.py -v` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: add local git commit source`.

---

### Task 4: Jira Cloud source

**Files:**
- Create: `src/standup_generator/sources/jira.py`
- Test: `tests/test_jira.py` (respx)

**Interfaces:**
- Consumes: `JiraConfig`, models.
- Produces: `JiraSource(cfg: JiraConfig, env: Mapping[str, str], client: httpx.Client | None = None)`, `name = "jira"`. Also `adf_to_text(node: dict | str | None) -> str` (concatenate `text` nodes depth-first; `paragraph`/`hardBreak` → newline; strip).
- Behaviour:
  - Missing `base_url` → error `"jira: set sources.jira.base_url"`; missing env var → `f"jira: set {cfg.email_env} / {cfg.token_env} in .env"`. No HTTP call made.
  - Basic auth (email, token). `GET /rest/api/3/myself` → `accountId`.
  - Flagged field: `GET /rest/api/3/field`, the field whose `name == "Flagged"`; absent → not requested.
  - Search via `POST /rest/api/3/search/jql` body `{jql, fields: ["summary","status","assignee","comment", <flagged>], maxResults: 100}`; follow `nextPageToken` up to cap 100.
  - JQL, dates formatted `"yyyy-MM-dd HH:mm"` from window (statuses double-quoted, optional ` AND project in (...)`):
    - in progress: `assignee = currentUser() AND status in (<in_progress>)`
    - completed: `status CHANGED TO (<handoff>) BY currentUser() DURING ("<start>", "<end>") AND status not in (<in_progress>)`
  - Completed tickets whose assignee accountId == myself are dropped when `exclude_if_reassigned_to_me`. A key in both results stays only as `in_progress`.
  - `Ticket.url = f"{base_url}/browse/{key}"`; `flagged` = flagged field non-empty; comments filtered to `created >= window.start`, body via `adf_to_text`, author `displayName`.
  - HTTP 401/403 → `"jira: authentication failed (401) — check JIRA_EMAIL / JIRA_API_TOKEN"`; 400 → `f"jira: query rejected — {errorMessages joined}. Check in_progress_statuses / handoff_statuses match your Jira workflow"`; network error → `f"jira: cannot reach {base_url}: {exc}"`.

- [ ] **Step 1: Write failing tests:**

```python
def test_missing_token_reports_error_without_http(window): ...
    # respx.mock(assert_all_called=False) with no routes; r.errors == ["jira: set JIRA_EMAIL / JIRA_API_TOKEN in .env"]
def test_in_progress_and_completed(window, jira_mock):
    r = src.collect(window)
    assert {t.key: t.category for t in r.tickets} == {"OFF-1": "in_progress", "OFF-2": "completed"}
def test_completed_jql_uses_by_current_user(window, jira_mock):
    # inspect captured request body: 'BY currentUser()' in jql and 'assignee = currentUser()' not in completed jql
def test_bounced_back_ticket_excluded(window, jira_mock_bounced):
    # OFF-3 completed but assignee accountId == myself → absent
def test_comments_filtered_to_window_and_plaintext(window, jira_mock):
    t = by_key["OFF-1"]; assert [c.body for c in t.comments] == ["Waiting on the platform team"]
def test_flagged(window, jira_mock): assert by_key["OFF-1"].flagged is True
def test_400_bad_status_is_readable_error(window):
    # search returns 400 {"errorMessages":["The value 'In QA' does not exist for the field 'status'."]}
    assert "does not exist" in r.errors[0] and "handoff_statuses" in r.errors[0]
def test_401(window): assert "authentication failed" in r.errors[0]
def test_adf_to_text():
    assert adf_to_text({"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"a"},{"type":"text","text":"b"}]}]}) == "ab"
```

- [ ] **Step 2: Run** `pytest tests/test_jira.py -v` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: add Jira Cloud ticket source`.

---

### Task 5: GitHub source

**Files:**
- Create: `src/standup_generator/sources/github.py`
- Test: `tests/test_github.py` (respx)

**Interfaces:**
- Produces: `GitHubSource(cfg: GitHubConfig, env: Mapping[str, str], client: httpx.Client | None = None)`, `name = "github"`.
- Behaviour:
  - Missing token → `f"github: set {cfg.token_env} in .env"`, no HTTP.
  - `GET {api_url}/search/issues?q=is:pr author:@me updated:>=<start YYYY-MM-DDTHH:MM:SSZ (UTC)>[ org:<o>...]&per_page=50`.
  - For each item: `GET /repos/{owner}/{repo}/pulls/{n}` → `head.ref`, `draft`, `merged_at`, `state`. State mapping: merged_at → `merged`; closed → `closed`; draft → `draft`; else `open`.
  - For `open` PRs only: `GET .../pulls/{n}/reviews`; `approved = any(r.state == "APPROVED")`.
  - A failing per-PR call adds an error line and keeps the PR with what the search item had (`head_branch=""`).
  - 401 → `"github: authentication failed — check GITHUB_TOKEN"`.

- [ ] **Step 1: Write failing tests:** `test_missing_token`, `test_maps_states` (one each merged/draft/open/closed), `test_open_pr_review_approved_flag`, `test_query_contains_author_and_date` (assert `author:@me` and `updated:>=2026-11-09` in captured URL), `test_per_pr_failure_keeps_pr_and_reports`, `test_401`.
- [ ] **Step 2: Run** `pytest tests/test_github.py -v` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: add GitHub pull request source`.

---

### Task 6: Source registry, correlation, blocker hints

**Files:**
- Create: `src/standup_generator/sources/registry.py`, `src/standup_generator/correlate.py`, `src/standup_generator/blockers.py`
- Test: `tests/test_registry.py`, `tests/test_correlate.py`, `tests/test_blockers.py`

**Interfaces:**
- Produces: `build_sources(cfg: AppConfig, env: Mapping[str, str]) -> tuple[list[Source], list[str]]` — enabled built-ins in order jira, github, git_local, then custom (`"pkg.mod:Class"` imported, instantiated as `Class(options=dict, env=env)`); second element is import errors as strings (`"custom: cannot load pkg.mod:Class: <exc>"`).
- Produces: `correlate(window: TimeWindow, results: list[SourceResult], key_pattern: str) -> ActivityBundle` (with `blocker_hints=[]`). Keys found with `re.IGNORECASE` in branch names, commit subjects, PR titles, normalized `.upper()`. A commit/PR attaches to every key it mentions. Keys with activity but no ticket → `other_tickets` entry with `Ticket(key, summary="", status="not found in any ticket source", url="", category="other", source="correlate")`. Tickets from any source with `category=="other"` also go to `other_tickets`. Duplicate keys across sources: first wins, `in_progress` beats `completed`. `source_errors`/`source_info` keyed by `SourceResult.source`.
- Produces: `find_blocker_hints(bundle: ActivityBundle, cfg: BlockersConfig, now: datetime) -> list[BlockerHint]` — reasons exactly `"flagged in Jira"`, `"comment mentions '<keyword>'"` (detail = first 200 chars of comment, case-insensitive match, one hint per comment), `"PR open without approval for <N>h"` (non-draft, `approved` is not True, `now - created_at >= stale_pr_hours`). Considers `in_progress` and `other_tickets` and `other_prs`.

- [ ] **Step 1: Write failing tests:**

```python
def test_lowercase_branch_key_normalized():
    c = Commit("a","r","fix stuff",T,["feat/off-1234-retry"])
    b = correlate(W, [SourceResult("git_local", commits=[c]), SourceResult("jira", tickets=[ticket("OFF-1234","in_progress")])], PATTERN)
    assert b.in_progress[0].commits == [c] and b.other_commits == []
def test_unmatched_commit_goes_to_other(): ...
def test_key_without_ticket_becomes_other_ticket():
    # assert b.other_tickets[0].ticket.status == "not found in any ticket source"
def test_in_progress_wins_over_completed_duplicate(): ...
def test_source_errors_collected(): ...
def test_registry_skips_disabled_and_reports_bad_custom(): 
    # custom path "nope.mod:X" → errors[0].startswith("custom: cannot load nope.mod:X")
def test_flagged_hint(); def test_keyword_hint_case_insensitive()  # "Waiting On infra" → reason "comment mentions 'waiting on'"
def test_stale_pr_hint_only_after_threshold(); def test_draft_pr_not_stale()
```

- [ ] **Step 2: Run** `pytest tests/test_registry.py tests/test_correlate.py tests/test_blockers.py -v` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: correlate activity to tickets and detect blocker hints`.

---

### Task 7: Prompt builder

**Files:**
- Create: `src/standup_generator/prompt.py`, `src/standup_generator/templates/prompt.md.j2`
- Test: `tests/test_prompt.py`

**Interfaces:**
- Produces: `build_prompt(bundle: ActivityBundle, plans: str, blockers: str, cfg: PromptConfig, today: date) -> str`. Loads `cfg.template_path` if set else packaged template (`importlib.resources`). Jinja2 env with `autoescape=False`, `trim_blocks=True`, filter `truncate_chars(text, n)` → text if `len<=n` else `text[:n-1] + "…"`.
- Template sections, in this order, with these exact headings: `## Instructions`, `## Context`, `## In progress`, `## Completed / moved to QA`, `## Other activity`, `## Blockers`, `## Data notes`.
  - Instructions must contain, verbatim: `Use only the facts provided below. Never invent work, tickets, or plans.` and the order `In progress → Completed / moved to QA → Blockers`, one or two spoken-style lines per ticket, include ticket keys, mention plans only where the user provided them.
  - `## Blockers`: user-entered blockers first under `Reported by me:`, then `Possible blockers — verify:` hints. Empty → `None reported.`
  - User plans rendered under `## In progress` as `My plans for today:` when non-empty.
  - `## Data notes`: one line per source with errors: `- <source> was unavailable: <error>. Missing data from this source does not mean no work was done.` Omit section when no errors.
  - Empty groups render `None.`

- [ ] **Step 1: Write failing tests:** `test_section_order`, `test_contains_no_invent_instruction`, `test_user_blockers_before_hints`, `test_comment_truncated` (600-char comment, `max_comment_chars=500` → 500-char body ending `…`), `test_source_error_note`, `test_no_data_notes_when_no_errors`, `test_plans_included_only_when_given`, `test_custom_template_path(tmp_path)`.
- [ ] **Step 2: Run** `pytest tests/test_prompt.py -v` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: build standup prompt from collected activity`.

---

### Task 8: History store

**Files:**
- Create: `src/standup_generator/history.py`
- Test: `tests/test_history.py`

**Interfaces:**
- Produces: `HistoryStore(db_path: Path)` — creates parent dirs and schema on init; `PRAGMA user_version = 1`.
  - Table `generations(id INTEGER PRIMARY KEY, created_at TEXT, updated_at TEXT, window_start TEXT, window_end TEXT, plans TEXT, blockers TEXT, prompt TEXT, source_errors TEXT, collected TEXT, final_standup TEXT NULL)`.
  - `add(result: GenerationResult, plans: str, blockers: str) -> int` (`collected` = `json.dumps(dataclasses.asdict(bundle), default=str)`).
  - `list(limit: int = 50) -> list[HistorySummary]`, newest first. `HistorySummary(id: int, created_at: str, window_start: str, window_end: str, has_final: bool, preview: str)` — preview = first non-empty line of `final_standup` or else of `plans`, else `""`, max 80 chars.
  - `get(id: int) -> HistoryEntry | None` — `HistoryEntry` dataclass with all columns (`source_errors`, `collected` parsed back from JSON).
  - `set_final(id: int, text: str) -> bool` (updates `updated_at`; False if no row).
  - `delete(id: int) -> bool`.
  - Connection per call (`sqlite3.connect`, `with` block) — safe across FastAPI threads.

- [ ] **Step 1: Write failing tests:** `test_creates_missing_parent_dirs(tmp_path)` (db at `tmp_path/"a/b/h.db"`), `test_add_get_roundtrip`, `test_list_newest_first_and_has_final`, `test_set_final_and_missing_id_returns_false`, `test_delete`, `test_user_version_is_1`.
- [ ] **Step 2: Run** `pytest tests/test_history.py -v` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: add SQLite history of generated prompts`.

---

### Task 9: Generator API + CLI

**Files:**
- Create: `src/standup_generator/generator.py`, `src/standup_generator/cli.py`; Modify: `src/standup_generator/__init__.py` (export `load_config`, `generate`, `AppConfig`, `GenerationResult`, `HistoryStore`)
- Test: `tests/test_generator.py`, `tests/test_cli.py`

**Interfaces:**
- Produces: `generate(config: AppConfig, plans: str = "", blockers: str = "", since: date | None = None, now: datetime | None = None, save: bool = False, sources: list[Source] | None = None, env: Mapping[str, str] | None = None) -> GenerationResult`.
  - `now` default `datetime.now(resolve_tz(config.timezone))`; `env` default `os.environ`; `sources` default `build_sources(...)` (registry errors recorded under source `"custom"`).
  - Sources run in `ThreadPoolExecutor`; any exception from `collect` → `SourceResult(source=s.name, errors=[f"{s.name}: unexpected error: {exc}"])`.
  - Pipeline: `compute_window` → collect → `correlate` → `find_blocker_hints` → `build_prompt(today=now.date())`.
  - `save and config.history.enabled` → `HistoryStore(config.history.db_path).add(...)`; `history_id` set, else `None`.
- Produces: `main(argv: list[str] | None = None) -> int` with subcommands:
  - `serve [--config] [--host 127.0.0.1] [--port 8765]` → `uvicorn.run(create_app(cfg), ...)` (import inside function).
  - `generate [--config] [--since YYYY-MM-DD] [--plans TEXT] [--blockers TEXT] [--no-save]` → prompt to stdout, each source error to stderr, exit 0 (exit 0 even with source errors; exit 2 on config error).
  - `init [--dir .]` → writes `standup.yaml` and `.env.example` from packaged copies; refuses to overwrite existing (`print` message, exit 1).
  - `history [--limit N]`, `history show ID`, `history save-final ID [--file PATH]` (stdin when no file).

- [ ] **Step 1: Write failing tests:**

```python
class Boom:  name = "boom";  def collect(self, w): raise RuntimeError("kaput")
class Fake:  name = "fake";  def collect(self, w): return SourceResult("fake", tickets=[ticket("OFF-1","in_progress")])
def test_exception_in_source_becomes_error(cfg):
    r = generate(cfg, sources=[Boom(), Fake()], now=NOW)
    assert r.bundle.source_errors["boom"] == ["boom: unexpected error: kaput"] and "OFF-1" in r.prompt
def test_save_writes_history(cfg_tmp_db):  r = generate(..., save=True); assert r.history_id == 1
def test_no_save_by_default(cfg_tmp_db): assert generate(...).history_id is None
def test_cli_generate_prints_prompt(capsys, monkeypatch)   # monkeypatch generator sources; assert "## Instructions" in out
def test_cli_init_refuses_overwrite(tmp_path)
def test_cli_history_save_final_from_file(tmp_path)
```

- [ ] **Step 2: Run** `pytest tests/test_generator.py tests/test_cli.py -v` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `pytest -v` → all PASS.
- [ ] **Step 5: Commit** `feat: add generate API and standup CLI`.

---

### Task 10: Web app + UI + README

**Files:**
- Create: `src/standup_generator/web/__init__.py`, `web/app.py`, `web/static/index.html`, `web/static/app.js`, `web/static/style.css`, `README.md`
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: `generate`, `HistoryStore`, `compute_window`.
- Produces: `create_app(config: AppConfig, sources: list[Source] | None = None) -> FastAPI` (`sources` for tests).
  - `GET /` → `index.html`; static at `/static`.
  - `GET /api/window?since=` → `{start, end}` ISO.
  - `POST /api/generate` body `{plans: str = "", blockers: str = "", since: date | None}` → `{id, prompt, window: {start,end}, errors: {source: [..]}, info: {...}, collected: <asdict bundle>}`; calls `generate(save=True)`.
  - `GET /api/history?limit=50`, `GET /api/history/{id}` (404 if missing), `PATCH /api/history/{id}` body `{final_standup: str}` (404 if missing), `DELETE /api/history/{id}` (204 / 404).
  - History endpoints return 404 with `{"detail": "history disabled"}` when `history.enabled` is false.
  - Host-header guard middleware: reject (400) any request whose `Host` hostname is not `localhost` or `127.0.0.1` (DNS-rebinding protection).
- UI (`index.html` + `app.js`, no build, no external scripts): window display + "since" date input; textareas "What I'm planning next" and "Blockers" (drafts in `localStorage`, wrapped in try/catch); **Generate** button with loading state; per-source error banners; prompt in read-only textarea with **Copy** (`navigator.clipboard`); "Paste the AI's standup here" textarea + **Save** → PATCH current id; collapsible "Collected data" (`<details>` with counts per group and pretty JSON); History panel list (date, window, ✓ when final exists, preview) → click loads entry into the view (prompt, final standup editable + Save, collected data) and **Delete** with `confirm()`. `style.css`: CSS variables with `prefers-color-scheme: dark`, max-width ~900px, system font.
- README: install (`uv venv --python 3.12`, `uv pip install -e .`), `standup init`, fill `.env` (Jira API token link `https://id.atlassian.com/manage-profile/security/api-tokens`, GitHub fine-grained token with read access to PRs), `standup serve`, `standup generate`, config reference pointing to `standup.example.yaml`, writing a custom source (class with `name` + `collect(window) -> SourceResult`, constructor `(options, env)`), where history lives.

- [ ] **Step 1: Write failing tests** (`fastapi.testclient.TestClient`, `base_url="http://127.0.0.1"`, fake source, tmp db):
  `test_index_served`, `test_generate_returns_id_and_prompt`, `test_patch_final_then_get`, `test_history_list_and_delete`, `test_get_missing_404`, `test_bad_host_rejected` (client with `base_url="http://evil.com"` → 400), `test_history_disabled_404`.
- [ ] **Step 2: Run** `pytest tests/test_web.py -v` → FAIL.
- [ ] **Step 3: Implement** `app.py`, static files, README.
- [ ] **Step 4: Run** `pytest -v` → all PASS.
- [ ] **Step 5: Manual check:** `standup serve --config standup.example.yaml`, open `http://127.0.0.1:8765`, click Generate with no tokens set → page shows Jira/GitHub "set … in .env" banners and a prompt with a Data notes section; paste text in final box, Save; reload → History shows ✓ entry. Stop server.
- [ ] **Step 6: Commit** `feat: add local web UI for generating and browsing standups`.
