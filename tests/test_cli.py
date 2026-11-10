from conftest import ticket

from standup_generator import cli, generator
from standup_generator.history import HistoryStore
from standup_generator.models import SourceResult


class Fake:
    name = "fake"

    def collect(self, w):
        return SourceResult("fake", tickets=[ticket("OFF-1")], errors=["fake: partial"])


def write_cfg(tmp_path):
    p = tmp_path / "standup.yaml"
    p.write_text(
        f"history:\n  db_path: {tmp_path / 'h.db'}\n"
        "sources:\n  jira: {enabled: false}\n  github: {enabled: false}\n  git_local: {enabled: false}\n"
    )
    return p


def test_cli_generate_prints_prompt(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(generator, "build_sources", lambda cfg, env: ([Fake()], []))
    code = cli.main(["generate", "--config", str(write_cfg(tmp_path)), "--plans", "do OFF-1"])
    out, err = capsys.readouterr()
    assert code == 0
    assert "## Instructions" in out and "do OFF-1" in out
    assert "fake: partial" in err
    assert HistoryStore(tmp_path / "h.db").get(1) is not None


def test_cli_generate_no_save(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(generator, "build_sources", lambda cfg, env: ([Fake()], []))
    cli.main(["generate", "--config", str(write_cfg(tmp_path)), "--no-save"])
    assert not (tmp_path / "h.db").exists()


def test_cli_bad_config_exits_2(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("working_days: [funday]\n")
    assert cli.main(["generate", "--config", str(bad)]) == 2
    assert "config" in capsys.readouterr().err.lower()


def test_cli_init_writes_files_and_refuses_overwrite(tmp_path, capsys):
    assert cli.main(["init", "--dir", str(tmp_path)]) == 0
    assert (tmp_path / "standup.yaml").is_file() and (tmp_path / ".env.example").is_file()
    assert cli.main(["init", "--dir", str(tmp_path)]) == 1


def test_cli_init_sets_jira_url_from_flag(tmp_path):
    assert cli.main(["init", "--dir", str(tmp_path), "--jira-url", "https://acme.atlassian.net/"]) == 0
    assert "JIRA_BASE_URL=https://acme.atlassian.net\n" in (tmp_path / ".env.example").read_text()


def test_cli_init_asks_for_jira_url_when_interactive(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", lambda prompt: "acme.atlassian.net")
    assert cli.main(["init", "--dir", str(tmp_path)]) == 0
    assert "JIRA_BASE_URL=https://acme.atlassian.net\n" in (tmp_path / ".env.example").read_text()


def test_cli_history_list_show_and_save_final(tmp_path, capsys, monkeypatch):
    cfg = str(write_cfg(tmp_path))
    monkeypatch.setattr(generator, "build_sources", lambda cfg, env: ([Fake()], []))
    cli.main(["generate", "--config", cfg])
    final = tmp_path / "final.txt"
    final.write_text("Yesterday I did OFF-1.")
    assert cli.main(["history", "--config", cfg, "save-final", "1", "--file", str(final)]) == 0
    capsys.readouterr()
    cli.main(["history", "--config", cfg])
    listing = capsys.readouterr().out
    assert "1" in listing and "Yesterday I did OFF-1." in listing
    cli.main(["history", "--config", cfg, "show", "1"])
    shown = capsys.readouterr().out
    assert "## Instructions" in shown and "Yesterday I did OFF-1." in shown
    assert cli.main(["history", "--config", cfg, "show", "99"]) == 1
