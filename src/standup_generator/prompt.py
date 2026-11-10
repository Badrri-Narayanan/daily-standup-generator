"""Render the standup prompt from collected activity."""

from __future__ import annotations

from datetime import date
from importlib import resources

from jinja2 import Environment

from .config import PromptConfig
from .models import ActivityBundle


def truncate_chars(text: str | None, n: int) -> str:
    text = text or ""
    return text if len(text) <= n else text[: n - 1] + "…"


def _env() -> Environment:
    env = Environment(autoescape=False, trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True)
    env.filters["truncate_chars"] = truncate_chars
    return env


def _template_source(cfg: PromptConfig) -> str:
    if cfg.template_path:
        return cfg.template_path.read_text()
    return resources.files("standup_generator").joinpath("templates/prompt.md.j2").read_text()


def build_prompt(bundle: ActivityBundle, plans: str, blockers: str, cfg: PromptConfig, today: date) -> str:
    template = _env().from_string(_template_source(cfg))
    return template.render(
        bundle=bundle,
        plans=(plans or "").strip(),
        blockers=(blockers or "").strip(),
        today=today.isoformat(),
        max_comment_chars=cfg.max_comment_chars,
    )
