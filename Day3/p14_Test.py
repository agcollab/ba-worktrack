"""P14: tests for the Task dataclass in p11_task.py.  Run with:  pytest -v"""
from datetime import date

import pytest

from p11_task import Priority, Status, Task, load_tasks, save_tasks


# ---------- fixture: a fresh task for every test that asks for one ----------
@pytest.fixture
def task() -> Task:
    return Task("Draft BRD", "Ankur")


# ---------- Exercise 1: five basic tests ----------
def test_new_task_starts_todo(task):
    assert task.status == Status.TODO
    assert task.priority == Priority.MEDIUM
    assert task.hours == 0.0
    assert task.due is None


def test_start_moves_to_in_progress(task):
    task.start()
    assert task.status == Status.IN_PROGRESS


def test_log_hours_adds_up(task):
    task.log_hours(2)
    task.log_hours(1.5)
    assert task.hours == 3.5


def test_complete_from_in_progress(task):
    task.start()
    task.complete()
    assert task.status == Status.DONE


def test_complete_from_todo_is_blocked(task):
    with pytest.raises(ValueError, match="In Progress"):
        task.complete()
    assert task.status == Status.TODO      # nothing changed after the error


# ---------- Exercise 2: parametrize (one test, many inputs) ----------
@pytest.mark.parametrize("bad", [0, -1, -0.5])
def test_bad_hours_rejected(task, bad):
    with pytest.raises(ValueError):
        task.log_hours(bad)
    assert task.hours == 0.0               # bad input must not change hours


# ---------- Exercise 3: round trip + tmp_path ----------
def test_dict_round_trip():
    t = Task("Write UAC", "Priya", priority=Priority.HIGH, due=date(2026, 10, 20))
    t.start()
    t.log_hours(4)

    data = t.to_dict()
    assert data["status"] == "In Progress"     # enum stored as plain text
    assert data["due"] == "2026-10-20"         # date stored as ISO text

    assert Task.from_dict(data) == t           # nothing lost on the way back


def test_save_and_load_json(tmp_path):
    # tmp_path is a fresh, empty folder pytest creates for this test only
    path = tmp_path / "tasks.json"
    tasks = [
        Task("Draft BRD", "Ankur", priority=Priority.HIGH, due=date(2026, 10, 20)),
        Task("Write UAC", "Priya", status=Status.DONE, hours=2.0),
        Task("Prepare UAT cases", "Rahul"),
    ]

    save_tasks(tasks, path)
    assert path.exists()

    loaded = load_tasks(path)
    assert loaded == tasks
    assert isinstance(loaded[0].due, date)
    assert isinstance(loaded[1].status, Status)