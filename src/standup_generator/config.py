"""Configuration loading: standup.yaml + .env."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

VALID_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _expand(p: Path | str) -> Path:
    return Path(p).expanduser()


class JiraConfig(BaseModel):
    enabled: bool = True
    base_url: str | None = None
    email_env: str = "JIRA_EMAIL"
    token_env: str = "JIRA_API_TOKEN"
    project_keys: list[str] = Field(default_factory=list)
    in_progress_statuses: list[str] = Field(
        default_factory=lambda: ["In Progress", "In Review", "Code Review"]
    )
    handoff_statuses: list[str] = Field(
        default_factory=lambda: ["QA", "Ready for QA", "In QA", "Done"]
    )
    exclude_if_reassigned_to_me: bool = True


class GitHubConfig(BaseModel):
    enabled: bool = True
    token_env: str = "GITHUB_TOKEN"
    api_url: str = "https://api.github.com"
    orgs: list[str] = Field(default_factory=list)


class GitLocalConfig(BaseModel):
    enabled: bool = True
    repos: list[Path] = Field(default_factory=list)
    scan_dirs: list[Path] = Field(default_factory=list)
    author_emails: list[str] = Field(default_factory=list)

    @field_validator("repos", "scan_dirs", mode="after")
    @classmethod
    def _expand_paths(cls, v: list[Path]) -> list[Path]:
        return [_expand(p) for p in v]


class CustomSourceConfig(BaseModel):
    path: str
    options: dict[str, Any] = Field(default_factory=dict)


class SourcesConfig(BaseModel):
    jira: JiraConfig = Field(default_factory=JiraConfig)
    github: GitHubConfig = Field(default_factory=GitHubConfig)
    git_local: GitLocalConfig = Field(default_factory=GitLocalConfig)
    custom: list[CustomSourceConfig] = Field(default_factory=list)


class BlockersConfig(BaseModel):
    keywords: list[str] = Field(
        default_factory=lambda: [
            "blocked", "blocker", "waiting on", "waiting for", "depends on", "stuck",
        ]
    )
    stale_pr_hours: int = 24


def _default_db_path() -> Path:
    return Path.home() / ".local/share/standup-generator/history.db"


class HistoryConfig(BaseModel):
    enabled: bool = True
    db_path: Path = Field(default_factory=_default_db_path)

    @field_validator("db_path", mode="after")
    @classmethod
    def _expand_db(cls, v: Path) -> Path:
        return _expand(v)


class PromptConfig(BaseModel):
    template_path: Path | None = None
    max_comment_chars: int = 500

    @field_validator("template_path", mode="after")
    @classmethod
    def _expand_template(cls, v: Path | None) -> Path | None:
        return _expand(v) if v else None


class AppConfig(BaseModel):
    timezone: str | None = None
    working_days: list[str] = Field(default_factory=lambda: ["mon", "tue", "wed", "thu", "fri"])
    holidays: list[date] = Field(default_factory=list)
    ticket_key_pattern: str = r"[A-Z][A-Z0-9]+-\d+"
    sources: SourcesConfig = Field(default_factory=SourcesConfig)
    blockers: BlockersConfig = Field(default_factory=BlockersConfig)
    history: HistoryConfig = Field(default_factory=HistoryConfig)
    prompt: PromptConfig = Field(default_factory=PromptConfig)

    @field_validator("working_days", mode="after")
    @classmethod
    def _check_days(cls, v: list[str]) -> list[str]:
        days = [d.lower() for d in v]
        bad = [d for d in days if d not in VALID_DAYS]
        if bad:
            raise ValueError(f"invalid working_days {bad}; use {list(VALID_DAYS)}")
        return days


def _find_config(path: str | Path | None) -> Path | None:
    if path is not None:
        p = _expand(path)
        if not p.is_file():
            raise FileNotFoundError(f"config file not found: {p}")
        return p
    for candidate in (Path.cwd() / "standup.yaml", Path.home() / ".config/standup/standup.yaml"):
        if candidate.is_file():
            return candidate
    return None


def load_config(path: str | Path | None = None) -> AppConfig:
    """Load config from ``path``, ./standup.yaml, ~/.config/standup/standup.yaml, or defaults.

    Also loads ``.env`` from the working directory and from the config file's directory.
    """
    load_dotenv(Path.cwd() / ".env")
    found = _find_config(path)
    data: dict[str, Any] = {}
    if found is not None:
        load_dotenv(found.parent / ".env")
        data = yaml.safe_load(found.read_text()) or {}
    return AppConfig.model_validate(data)
