# Daily Standup Generator — Design

Date: 2026-11-10
Status: Approved 2026-11-10

## 1. Intent

Every morning the user reconstructs "what did I do yesterday" by checking their
in-progress Jira tickets, recalling commits/PRs, reading ticket comments, and
remembering blockers. This tool automates the gathering step and produces a
**ready-to-paste LLM prompt** that the user feeds into whichever AI they prefer
to get a polished standup update.

The tool **does not call any AI itself**. It is a data collector + prompt builder.

## 2. The user's standup structure (must be preserved in the prompt)

1. **In progress** — each ticket currently being worked on, with a brief status
   (based on commits/PRs from the last working day and this morning, ticket
   comments, and what the user plans next).
2. **Completed / moved to QA** — tickets the user handed off to QA since the
   last working day. "Completed" means: **the user** moved it to a QA/done
   status in the window, and it has **not** come back — it is not currently in
   an in-progress status and not assigned back to the user. Tickets moved by
   someone else (e.g. QA closing it) do not count.
3. **Blockers** — anything stopping progress (sometimes in ticket comments,
   often only in the user's head).

## 3. Goals

- Local web app: start one command, open `http://localhost:<port>`, click
  **Generate**, copy the prompt.
- Gather from Jira, GitHub, and local git repos for the window
  "start of last working day → now".
- Let the user add free-text **plans** and **blockers** before generating; these
  are merged into the prompt.
- Auto-detect *likely* blockers as hints (never authoritative).
- Keep a local **history** of generated prompts in SQLite, stored outside the
  git repo (see §6.10).
- Generic and extensible: sources are pluggable adapters; usable as an
  importable Python library without the web UI. Any source may supply tickets
  (not only Jira): `Ticket` carries a `category` (`in_progress` | `completed` |
  `other`) set by the source, and correlation works across all ticket sources.
- Sensible defaults so it works with minimal config: Jira Cloud + GitHub +
  local git.

## 4. Non-goals

- Calling an LLM / storing API keys for an LLM.
- Posting to Slack/Teams/anywhere.
- Multi-user / hosted deployment. **Single user only** — the user's personal
  tool. Moving teams is handled by editing config, not by product features.
- Polished onboarding, versioned plugin API, or docs for other people.
- Modifying Jira or GitHub (strictly read-only).

## 5. Anti-goals (failure even if it "works")

- Inventing work or plans the user didn't do / state.
- Silently dropping a source failure (e.g. Jira auth fails and the prompt just
  looks empty). Errors must be visible per source.
- Requiring heavy setup (database servers, frontend build steps, Docker).
  A local SQLite file created automatically is fine.
- Committing personal data (history DB, `.env`) to git.
- Hard-coding one company's Jira workflow status names.

## 6. Architecture

```
standup_generator/
  config.py          # load YAML config + .env, validate (pydantic)
  window.py          # last-working-day time window computation
  models.py          # normalized dataclasses: Ticket, Comment, Commit, PullRequest, ActivityBundle
  sources/
    base.py          # Source protocol: name, collect(window, ctx) -> SourceResult
    jira.py          # Jira Cloud REST v3 adapter
    github.py        # GitHub REST/search adapter
    git_local.py     # local repos via `git log` subprocess
    registry.py      # entry-point / dotted-path based registration
  correlate.py       # attach commits/PRs to tickets by ticket key regex
  blockers.py        # heuristic blocker hints
  prompt.py          # build final prompt from ActivityBundle + user notes (Jinja2 template)
  generator.py       # public API: generate(config, notes) -> GenerationResult
  web/
    app.py           # FastAPI app
    static/index.html, app.js, style.css   # plain HTML/JS, no build step
  history.py         # SQLite history store (stdlib sqlite3)
  cli.py             # `standup serve`, `standup generate` (prints prompt to stdout)
```

### 6.1 Source interface

```python
class Source(Protocol):
    name: str
    def collect(self, window: TimeWindow, ctx: SourceContext) -> SourceResult: ...
```

`SourceResult` holds normalized items (tickets, comments, commits, PRs) plus
`errors: list[str]`. One source failing must not prevent others from running;
errors are surfaced in the UI/CLI only; the generated prompt includes a short
note that a source was unavailable so the AI doesn't treat missing data as "no work".

Custom sources are registered in config by dotted path
(`my_pkg.sources:GitLabSource`) — that is the extension mechanism.

### 6.2 Time window

- Default: from 00:00 local time of the **previous working day** to now.
- Working days default Mon–Fri (configurable list). Monday → Friday 00:00.
- Optional `holidays: [YYYY-MM-DD, ...]` skipped when walking back.
- UI/CLI override: `--since YYYY-MM-DD`.
- Timezone: system local unless `timezone` set in config.

### 6.3 Default sources

**Jira Cloud** (`base_url`, `email`, `api_token` from env — `JIRA_BASE_URL` in `.env`, falling back to `sources.jira.base_url`)
- In progress: JQL `assignee = currentUser() AND status in (<in_progress_statuses>)`.
- Completed (handed off by me): JQL
  `status CHANGED TO (<handoff_statuses>) BY currentUser() DURING (<start>, <end>)
   AND status not in (<in_progress_statuses>)`
  — deliberately **no** `assignee = currentUser()`, since tickets are usually
  reassigned to QA. Then, if `exclude_if_reassigned_to_me` (default true),
  drop tickets whose current assignee is the user (they've bounced back).
  A ticket in both groups appears only under In progress.
- For each ticket: key, summary, status, URL, flagged state, comments created
  within the window (all authors — teammates' comments matter).
- Status lists are config, defaults: in progress `["In Progress", "In Review", "Code Review"]`,
  handoff `["QA", "Ready for QA", "In QA", "Done"]`.
- Optional `project_keys` filter.

**GitHub** (`token` from env, optional `api_url` for GHE)
- PRs authored by the user updated within the window: `search/issues?q=is:pr author:@me updated:>=<start>`.
- Captures: number, title, repo, URL, state (open/merged/closed/draft),
  head branch, review state if cheaply available, created/merged dates.
- Optional `orgs`/`repos` filter.

**Local git** (`repos: [paths]` or `scan_dirs: [paths]` with depth 2)
- `git log --all --author=<email> --since=<start> --format=...` per repo.
- Captures sha, repo name, branch(es) if resolvable, subject, timestamp.
- Author emails list in config (default: `git config user.email`).

### 6.4 Correlation

- Ticket key regex default `[A-Z][A-Z0-9]+-\d+` (configurable).
- Commit/PR attached to ticket if key appears in branch name, commit subject,
  or PR title.
- Unmatched commits/PRs go to an "Other activity" group in the prompt.
- Tickets found only via commits/PRs (not in Jira results) are listed with
  key only, flagged "not found in any ticket source".

### 6.5 Blocker hints

Heuristic, labeled as "possible blockers — verify" in the prompt:
- Jira ticket flagged (Impediment).
- Comment in window matching configurable keywords
  (default: `blocked`, `blocker`, `waiting on`, `waiting for`, `depends on`, `stuck`).
- Open non-draft PR with no approving review older than N hours (default 24).

User-entered blockers are always treated as authoritative and listed first.

### 6.6 Prompt output

Rendered from a Jinja2 template; default template shipped in package, override
via `prompt.template_path` in config. Default prompt contains:

1. Instructions to the AI: write a concise spoken-style standup in the order
   In progress → Completed/moved to QA → Blockers; one or two lines per
   ticket; **use only the facts provided, never invent work**; include ticket
   keys; mention plans only where the user provided them.
2. Context: date, window covered.
3. Data: per ticket (status, summary, linked commits, PRs, new comments,
   truncated to a configurable max length), completed tickets, other activity,
   possible blockers.
4. User notes: plans, blockers (verbatim).

Plain text/Markdown, no secrets (tokens never rendered).

### 6.7 Web UI

Single page:
- Window display + optional "since" date override.
- Textarea: "What I'm planning next" (optional).
- Textarea: "Blockers" (optional).
- **Generate** button → POST `/api/generate`.
- Result: prompt in a read-only textarea with **Copy** button; collapsible
  "Collected data" panel (per source, with item counts); per-source error
  banners.
- Draft notes kept in `localStorage` for convenience.
- Binds to `127.0.0.1` only by default.

### 6.8 Library API

```python
from standup_generator import load_config, generate
result = generate(load_config("standup.yaml"), plans="...", blockers="...")
print(result.prompt)
```

### 6.9 CLI

- `standup serve [--config PATH] [--port 8765]`
- `standup generate [--config PATH] [--since DATE] [--plans TEXT] [--blockers TEXT]` → prompt on stdout.
- `standup init` → writes example `standup.yaml` and `.env.example`.

### 6.10 History (SQLite)

- Stdlib `sqlite3`, no ORM. File location default
  `~/.local/share/standup-generator/history.db` (override `history.db_path`);
  directory created on first use. **Never inside the repo**; `.gitignore` also
  ignores `*.db` / `*.sqlite*` as a safety net.
- Every successful generate (UI, CLI, library when `save=True`, default true
  for UI/CLI) inserts one row.
- Table `generations`: `id`, `created_at` (UTC ISO), `window_start`,
  `window_end`, `plans`, `blockers`, `prompt`, `source_errors` (JSON),
  `collected` (JSON snapshot of the normalized ActivityBundle — no secrets),
  `final_standup` (nullable text — the AI's answer, pasted back by the user),
  `updated_at`.
- Schema versioned via `PRAGMA user_version`; simple forward migrations in code.
- UI: after Generate, a "Paste the AI's standup here" box under the prompt
  with **Save**; it saves to the row just created. "History" panel lists past
  generations (date, window, whether a final standup exists, first line);
  click to view/copy the prompt, the final standup, and the collected data;
  add/edit the final standup later; delete a single entry.
- API: `GET /api/history`, `GET /api/history/{id}`,
  `PATCH /api/history/{id}` (body `{final_standup}`), `DELETE /api/history/{id}`.
  `POST /api/generate` returns the new history `id`.
- CLI: `standup history [--limit N]`, `standup history show ID`,
  `standup history save-final ID [--file PATH | stdin]`.
- `history.enabled: false` turns it off entirely.

## 7. Configuration

`standup.yaml` (lookup order: `--config`, `./standup.yaml`, `~/.config/standup/standup.yaml`):

```yaml
timezone: Europe/London        # optional
working_days: [mon, tue, wed, thu, fri]
holidays: []
ticket_key_pattern: "[A-Z][A-Z0-9]+-\\d+"
sources:
  jira:
    enabled: true
    base_url_env: JIRA_BASE_URL    # .env value wins over base_url below
    # base_url: https://acme.atlassian.net
    email_env: JIRA_EMAIL
    token_env: JIRA_API_TOKEN
    project_keys: []
    in_progress_statuses: ["In Progress", "In Review", "Code Review"]
    handoff_statuses: ["QA", "Ready for QA", "In QA", "Done"]
    exclude_if_reassigned_to_me: true   # set false if your team doesn't reassign to QA
  github:
    enabled: true
    token_env: GITHUB_TOKEN
    api_url: https://api.github.com
    orgs: []
  git_local:
    enabled: true
    repos: []
    scan_dirs: ["~/code"]
    author_emails: []          # default: git config user.email
  custom: []                   # e.g. [{path: "my_pkg.sources:GitLabSource", options: {...}}]
blockers:
  keywords: [blocked, blocker, "waiting on", "waiting for", "depends on", stuck]
  stale_pr_hours: 24
history:
  enabled: true
  db_path: ~/.local/share/standup-generator/history.db
prompt:
  template_path: null
  max_comment_chars: 500
```

Secrets only from environment / `.env` (python-dotenv). Disabled or
unconfigured sources are skipped with an info note, not an error.

## 8. Tech choices (builder's call, stated)

- Python 3.11+, packaged with `pyproject.toml`, installable via `pip install -e .`.
- FastAPI + uvicorn, httpx for HTTP, pydantic for config, Jinja2 for prompt,
  python-dotenv, PyYAML. No frontend build step.
- Tests: pytest; HTTP sources tested with mocked httpx (respx); git source
  tested against a temp repo created in the test.

## 9. Error handling

- Each source runs independently; exceptions are caught and reported as
  `SourceResult.errors` with a human-readable message (e.g. "Jira: 401 —
  check JIRA_EMAIL / JIRA_API_TOKEN").
- Network timeouts default 15s per request.
- UI shows partial results plus errors; CLI prints errors to stderr and the
  prompt to stdout.

## 10. Left to the builder

- Exact HTML styling (keep it clean and minimal, light/dark).
- Pagination limits (sane caps, e.g. 100 tickets, 200 commits).
- Whether sources run concurrently (nice to have).
- Exact prompt wording within the constraints of §6.6.
