"""Tests for mini_api.py. Run (from crash-course/api):  pytest -v

TestClient calls the API in memory - no server needs to be running.
"""
import pytest
from fastapi.testclient import TestClient

import mini_api

client = TestClient(mini_api.app)


@pytest.fixture(autouse=True)          # autouse: runs before EVERY test automatically
def clean_db():
    mini_api.reset_db()


def test_create_returns_201_and_id():
    resp = client.post("/tasks", json={"title": "Write UAC"})
    assert resp.status_code == 201
    assert resp.json() == {"id": 1, "title": "Write UAC", "status": "To Do", "hours": 0}


def test_get_missing_task_is_404():
    resp = client.get("/tasks/99")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Task 99 not found"


def test_bad_status_is_422():
    resp = client.post("/tasks", json={"title": "X", "status": "Finished"})
    assert resp.status_code == 422      # Pydantic rejected it before our code ran


def test_negative_hours_is_422():
    resp = client.post("/tasks", json={"title": "X", "hours": -1})
    assert resp.status_code == 422


def test_patch_changes_only_sent_fields():
    client.post("/tasks", json={"title": "Draft BRD", "hours": 2})
    resp = client.patch("/tasks/1", json={"status": "Done"})
    assert resp.status_code == 200
    assert resp.json() == {"id": 1, "title": "Draft BRD", "status": "Done", "hours": 2}


def test_filter_by_status():
    client.post("/tasks", json={"title": "A"})
    client.post("/tasks", json={"title": "B", "status": "Done"})
    resp = client.get("/tasks", params={"status": "Done"})
    assert [t["title"] for t in resp.json()] == ["B"]


def test_delete_then_get_is_404():
    client.post("/tasks", json={"title": "Temp"})
    assert client.delete("/tasks/1").status_code == 204
    assert client.get("/tasks/1").status_code == 404


def test_ids_not_reused_after_delete():
    client.post("/tasks", json={"title": "A"})          # id 1
    client.post("/tasks", json={"title": "B"})          # id 2
    client.delete("/tasks/1")
    resp = client.post("/tasks", json={"title": "C"})
    assert resp.json()["id"] == 3                        # len(tasks)+1 would give 2: a clash!
