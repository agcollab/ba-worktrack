"""The JSON API with Bearer tokens."""
from datetime import date

from tests.conftest import PASSWORD


def token(client, email="asha@test.com"):
    response = client.post("/api/v1/auth/token", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_api_requires_auth(client):
    assert client.get("/api/v1/tasks").status_code == 401


def test_bad_login(client, people):
    response = client.post("/api/v1/auth/token", json={"email": "asha@test.com", "password": "nope"})
    assert response.status_code == 400


def test_create_move_and_log_time(client, people):
    headers = token(client)
    created = client.post("/api/v1/tasks", headers=headers, json={"project_id": people["pay"].id, "title": "API task",
                                                                   "estimate_hours": 3})
    assert created.status_code == 201
    task = created.json()
    assert task["key"].startswith("PAY-") and task["status"] == "To Do"

    moved = client.post(f"/api/v1/tasks/{task['id']}/status", headers=headers, json={"status": "In Progress"})
    assert moved.json()["status"] == "In Progress"
    bad = client.post(f"/api/v1/tasks/{task['id']}/status", headers=headers, json={"status": "Done"})
    assert bad.status_code == 400

    entry = client.post("/api/v1/time-entries", headers=headers,
                        json={"task_id": task["id"], "work_date": date.today().isoformat(), "hours": 1.5})
    assert entry.status_code == 201
    assert client.get(f"/api/v1/tasks/{task['id']}", headers=headers).json()["total_hours"] == 1.5

    patched = client.patch(f"/api/v1/tasks/{task['id']}", headers=headers, json={"title": "Renamed"})
    assert patched.json()["title"] == "Renamed"


def test_api_respects_project_visibility(client, people):
    headers = token(client)
    response = client.post("/api/v1/tasks", headers=headers, json={"project_id": people["crm"].id, "title": "Nope"})
    assert response.status_code == 403
    assert [p["key"] for p in client.get("/api/v1/projects", headers=headers).json()] == ["PAY"]


def test_metrics_summary(client, people):
    headers = token(client, "pm@test.com")
    data = client.get("/api/v1/metrics/summary", headers=headers).json()
    assert {"total_hours", "tasks_completed", "overdue"} <= set(data)
