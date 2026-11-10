import sqlite3

from conftest import ticket

from standup_generator.history import HistoryStore
from standup_generator.models import ActivityBundle, GenerationResult, TicketActivity


def result(window, prompt="PROMPT"):
    b = ActivityBundle(window=window, in_progress=[TicketActivity(ticket("OFF-1"))],
                       source_errors={"github": ["github: down"]})
    return GenerationResult(prompt=prompt, bundle=b)


def test_creates_missing_parent_dirs(tmp_path, window):
    db = tmp_path / "a" / "b" / "h.db"
    HistoryStore(db).add(result(window), "", "")
    assert db.is_file()


def test_add_get_roundtrip(tmp_path, window):
    s = HistoryStore(tmp_path / "h.db")
    i = s.add(result(window), "plan A", "blocked on B")
    e = s.get(i)
    assert e.prompt == "PROMPT" and e.plans == "plan A" and e.blockers == "blocked on B"
    assert e.source_errors == {"github": ["github: down"]}
    assert e.collected["in_progress"][0]["ticket"]["key"] == "OFF-1"
    assert e.window_start.startswith("2026-11-09") and e.final_standup is None


def test_list_newest_first_and_has_final(tmp_path, window):
    s = HistoryStore(tmp_path / "h.db")
    a = s.add(result(window), "first plans", "")
    b = s.add(result(window), "", "")
    s.set_final(a, "\nYesterday I finished OFF-1.\nToday more.")
    rows = s.list()
    assert [r.id for r in rows] == [b, a]
    assert rows[1].has_final is True and rows[1].preview == "Yesterday I finished OFF-1."
    assert rows[0].has_final is False and rows[0].preview == ""


def test_list_limit(tmp_path, window):
    s = HistoryStore(tmp_path / "h.db")
    for _ in range(3):
        s.add(result(window), "", "")
    assert len(s.list(limit=2)) == 2


def test_set_final_and_missing_id_returns_false(tmp_path, window):
    s = HistoryStore(tmp_path / "h.db")
    i = s.add(result(window), "", "")
    assert s.set_final(i, "done") is True
    assert s.get(i).final_standup == "done"
    assert s.set_final(999, "x") is False


def test_delete(tmp_path, window):
    s = HistoryStore(tmp_path / "h.db")
    i = s.add(result(window), "", "")
    assert s.delete(i) is True and s.get(i) is None and s.delete(i) is False


def test_user_version_is_1(tmp_path, window):
    db = tmp_path / "h.db"
    HistoryStore(db)
    with sqlite3.connect(db) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
