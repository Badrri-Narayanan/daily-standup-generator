"""Public entry point: collect from every source and build the prompt."""

from __future__ import annotations

import os
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

from .blockers import find_blocker_hints
from .config import AppConfig
from .correlate import correlate
from .history import HistoryStore
from .models import GenerationResult, SourceResult, TimeWindow
from .prompt import build_prompt
from .sources.base import Source
from .sources.registry import build_sources
from .window import compute_window, resolve_tz


def _safe_collect(source: Source, window: TimeWindow) -> SourceResult:
    try:
        return source.collect(window)
    except Exception as exc:  # a broken source must never sink the whole run
        return SourceResult(source=source.name, errors=[f"{source.name}: unexpected error: {exc}"])


def generate(
    config: AppConfig,
    plans: str = "",
    blockers: str = "",
    since: date | None = None,
    now: datetime | None = None,
    save: bool = False,
    sources: list[Source] | None = None,
    env: Mapping[str, str] | None = None,
) -> GenerationResult:
    now = now or datetime.now(resolve_tz(config.timezone))
    env = os.environ if env is None else env
    window = compute_window(now, config.working_days, config.holidays, since)

    results: list[SourceResult] = []
    if sources is None:
        sources, registry_errors = build_sources(config, env)
        if registry_errors:
            results.append(SourceResult(source="custom", errors=registry_errors))

    if sources:
        with ThreadPoolExecutor(max_workers=len(sources)) as pool:
            results.extend(pool.map(lambda s: _safe_collect(s, window), sources))

    bundle = correlate(window, results, config.ticket_key_pattern, config.sources.jira.project_keys)
    bundle.blocker_hints = find_blocker_hints(bundle, config.blockers, now)
    prompt = build_prompt(bundle, plans, blockers, config.prompt, now.date())
    result = GenerationResult(prompt=prompt, bundle=bundle)

    if save and config.history.enabled:
        result.history_id = HistoryStore(config.history.db_path).add(result, plans, blockers)
    return result
