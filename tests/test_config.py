from pathlib import Path

import pytest

from standup_generator.config import load_config

ROOT = Path(__file__).parent.parent


def test_defaults_when_no_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = load_config()
    assert cfg.working_days == ["mon", "tue", "wed", "thu", "fri"]
    assert cfg.sources.jira.in_progress_statuses == ["In Progress", "In Review", "Code Review"]
    assert cfg.sources.jira.handoff_statuses == ["QA", "Ready for QA", "In QA", "Done"]
    assert cfg.sources.jira.exclude_if_reassigned_to_me is True
    assert cfg.blockers.stale_pr_hours == 24
    assert cfg.blockers.keywords == ["blocked", "blocker", "waiting on", "waiting for", "depends on", "stuck"]
    assert cfg.prompt.max_comment_chars == 500
    assert cfg.ticket_key_pattern == r"[A-Z][A-Z0-9]+-\d+"
    assert cfg.history.db_path == tmp_path / ".local/share/standup-generator/history.db"


def test_explicit_file_overrides(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text("sources:\n  jira:\n    handoff_statuses: [QA]\n  git_local:\n    repos: ['~/x']\n")
    cfg = load_config(p)
    assert cfg.sources.jira.handoff_statuses == ["QA"]
    assert cfg.sources.git_local.repos == [Path.home() / "x"]


def test_cwd_standup_yaml_is_used(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "standup.yaml").write_text("timezone: Europe/London\n")
    assert load_config().timezone == "Europe/London"


def test_invalid_working_day_rejected(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text("working_days: [funday]\n")
    with pytest.raises(ValueError):
        load_config(p)


def test_example_config_loads():
    cfg = load_config(ROOT / "src/standup_generator/templates/standup.example.yaml")
    assert cfg.sources.jira.base_url
