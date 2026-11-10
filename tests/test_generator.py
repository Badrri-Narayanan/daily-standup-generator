from datetime import datetime

from conftest import UTC, ticket

from standup_generator.config import AppConfig, HistoryConfig
from standup_generator.generator import generate
from standup_generator.history import HistoryStore
from standup_generator.models import SourceResult

NOW = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)


class Boom:
    name = "boom"

    def collect(self, w):
        raise RuntimeError("kaput")


class Fake:
    name = "fake"

    def __init__(self):
        self.window = None

    def collect(self, w):
        self.window = w
        return SourceResult("fake", tickets=[ticket("OFF-1")])


def cfg(tmp_path, **kw):
    return AppConfig(history=HistoryConfig(db_path=tmp_path / "h.db"), **kw)


def test_exception_in_source_becomes_error(tmp_path):
    r = generate(cfg(tmp_path), sources=[Boom(), Fake()], now=NOW)
    assert r.bundle.source_errors["boom"] == ["boom: unexpected error: kaput"]
    assert "OFF-1" in r.prompt and "boom was unavailable" in r.prompt


def test_window_passed_to_sources_and_since(tmp_path):
    f = Fake()
    generate(cfg(tmp_path), sources=[f], now=NOW)
    assert f.window.start == datetime(2026, 11, 9, 0, 0, tzinfo=UTC)
    from datetime import date
    generate(cfg(tmp_path), sources=[f], now=NOW, since=date(2026, 11, 2))
    assert f.window.start.date() == date(2026, 11, 2)


def test_plans_and_blockers_in_prompt(tmp_path):
    r = generate(cfg(tmp_path), plans="ship OFF-1", blockers="need access", sources=[Fake()], now=NOW)
    assert "ship OFF-1" in r.prompt and "need access" in r.prompt


def test_save_writes_history(tmp_path):
    r = generate(cfg(tmp_path), plans="p", sources=[Fake()], now=NOW, save=True)
    assert r.history_id == 1
    assert HistoryStore(tmp_path / "h.db").get(1).plans == "p"


def test_no_save_by_default(tmp_path):
    assert generate(cfg(tmp_path), sources=[Fake()], now=NOW).history_id is None
    assert not (tmp_path / "h.db").exists()


def test_save_ignored_when_history_disabled(tmp_path):
    c = cfg(tmp_path)
    c.history.enabled = False
    assert generate(c, sources=[Fake()], now=NOW, save=True).history_id is None


def test_registry_errors_recorded_as_custom(tmp_path):
    from standup_generator.config import CustomSourceConfig
    c = cfg(tmp_path)
    c.sources.jira.enabled = c.sources.github.enabled = c.sources.git_local.enabled = False
    c.sources.custom = [CustomSourceConfig(path="nope:X")]
    r = generate(c, now=NOW, env={})
    assert r.bundle.source_errors["custom"][0].startswith("custom: cannot load nope:X")
