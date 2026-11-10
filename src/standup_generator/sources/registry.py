"""Build the list of enabled sources from config, including custom ones."""

from __future__ import annotations

import importlib
from collections.abc import Mapping

from ..config import AppConfig
from .base import Source
from .git_local import GitLocalSource
from .github import GitHubSource
from .jira import JiraSource


def _load_custom(path: str, options: dict, env: Mapping[str, str]) -> Source:
    module_name, _, attr = path.partition(":")
    if not module_name or not attr:
        raise ValueError("expected 'package.module:ClassName'")
    cls = getattr(importlib.import_module(module_name), attr)
    return cls(options=options, env=env)


def build_sources(cfg: AppConfig, env: Mapping[str, str]) -> tuple[list[Source], list[str]]:
    sources: list[Source] = []
    errors: list[str] = []
    s = cfg.sources
    if s.jira.enabled:
        sources.append(JiraSource(s.jira, env))
    if s.github.enabled:
        sources.append(GitHubSource(s.github, env))
    if s.git_local.enabled:
        sources.append(GitLocalSource(s.git_local))
    for custom in s.custom:
        try:
            sources.append(_load_custom(custom.path, custom.options, env))
        except Exception as exc:  # any import/constructor failure is reported, not raised
            errors.append(f"custom: cannot load {custom.path}: {exc}")
    return sources, errors
