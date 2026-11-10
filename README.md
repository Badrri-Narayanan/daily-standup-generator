# Daily Standup Generator

A small local web app (and Python library) that collects what you did since the
last working day — Jira tickets, GitHub PRs, local git commits, ticket comments —
and builds a **ready-to-paste prompt** for whatever AI you like. It never calls an
AI itself and never writes to Jira or GitHub.

The prompt follows this order: **In progress → Completed / moved to QA → Blockers**.

## Install

Requires Python 3.11+. With [uv](https://github.com/astral-sh/uv):

```bash
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e .
```

## Set up

```bash
standup init                 # writes standup.yaml and .env.example here
cp .env.example .env         # then fill in your tokens
```

- `JIRA_EMAIL` / `JIRA_API_TOKEN` — create a token at
  https://id.atlassian.com/manage-profile/security/api-tokens
- `GITHUB_TOKEN` — a fine-grained token with read access to pull requests
  (and metadata) on the repos/orgs you work in.

Then edit `standup.yaml`:

- `sources.jira.base_url` — e.g. `https://yourco.atlassian.net`
- `sources.jira.in_progress_statuses` / `handoff_statuses` — **must match your Jira
  workflow names**. If they don't, the page shows a "query rejected" error.
- `sources.git_local.scan_dirs` or `repos` — where your repos live.
- `exclude_if_reassigned_to_me` — set `false` if your team doesn't reassign
  tickets to QA.

Config is looked up at `--config PATH`, then `./standup.yaml`, then
`~/.config/standup/standup.yaml`. `.env` is read from the current directory and
from the config file's directory.

## Use

```bash
standup serve                # open http://127.0.0.1:8765
```

1. Optionally type your plans and blockers.
2. Click **Generate**, then **Copy prompt** and paste it into your AI.
3. Paste the AI's answer back into "Paste the AI's standup here" and **Save**.

Terminal-only:

```bash
standup generate --plans "Finish OFF-1234 tests" > prompt.md
standup history                       # ✓ = final standup saved
standup history show 12
pbpaste | standup history save-final 12
```

## What counts as what

- **In progress** — assigned to you, status in `in_progress_statuses`.
- **Completed / moved to QA** — *you* moved it into a `handoff_statuses` status in
  the window, and it hasn't come back (not in progress again, not reassigned to you).
- **Possible blockers** — flagged tickets, comments mentioning `blockers.keywords`,
  and open PRs without approval older than `stale_pr_hours`. Labeled "verify";
  what you type in Blockers is listed first.
- Commits and PRs are matched to tickets by the key in the branch name, commit
  message or PR title (case-insensitive, e.g. `feat/off-1234-retry`).
- The window starts at midnight of the previous working day (`working_days`,
  `holidays`); override with **Since** / `--since`.

## History

Stored in SQLite at `~/.local/share/standup-generator/history.db` (change with
`history.db_path`, disable with `history.enabled: false`). It's outside the repo,
and `.gitignore` excludes `*.db` and `.env` as a safety net.

## Use as a library

```python
from standup_generator import load_config, generate

result = generate(load_config(), plans="Pair with QA on OFF-1301", save=False)
print(result.prompt)
```

## Custom prompt

Copy `src/standup_generator/templates/prompt.md.j2`, edit it, and set
`prompt.template_path`. The template gets `bundle`, `plans`, `blockers`, `today`
and the `truncate_chars` filter.

## Custom sources

Any class with a `name` and `collect(window) -> SourceResult` works. Its
constructor receives `options` (from config) and `env`:

```python
from standup_generator.models import SourceResult, Ticket

class LinearSource:
    name = "linear"
    def __init__(self, options, env):
        self.token = env.get(options.get("token_env", "LINEAR_TOKEN"))
    def collect(self, window):
        return SourceResult(self.name, tickets=[...])  # Ticket(category="in_progress"|"completed"|"other", ...)
```

```yaml
sources:
  custom:
    - path: my_sources:LinearSource
      options: {token_env: LINEAR_TOKEN}
```

## Development

```bash
uv pip install -e ".[dev]"
pytest
```
