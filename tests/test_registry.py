from standup_generator.config import AppConfig, CustomSourceConfig
from standup_generator.sources.registry import build_sources


class Dummy:
    name = "dummy"

    def __init__(self, options, env):
        self.options = options

    def collect(self, window):
        raise NotImplementedError


def test_builtin_order_and_disabled_skipped():
    cfg = AppConfig()
    cfg.sources.github.enabled = False
    sources, errors = build_sources(cfg, {})
    assert [s.name for s in sources] == ["jira", "git_local"] and errors == []


def test_custom_source_loaded_with_options():
    cfg = AppConfig()
    cfg.sources.custom = [CustomSourceConfig(path="test_registry:Dummy", options={"a": 1})]
    sources, errors = build_sources(cfg, {})
    assert errors == []
    assert sources[-1].name == "dummy" and sources[-1].options == {"a": 1}


def test_bad_custom_reported():
    cfg = AppConfig()
    cfg.sources.custom = [CustomSourceConfig(path="nope.mod:X")]
    sources, errors = build_sources(cfg, {})
    assert errors[0].startswith("custom: cannot load nope.mod:X")
    assert [s.name for s in sources] == ["jira", "github", "git_local"]
