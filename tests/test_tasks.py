"""Tasks: creating, visibility per project, the status workflow, comments, files, board."""
import pytest

from app.models import Task, TaskComment, TaskStatus, TaskStatusHistory
from app.services import tasks as task_service
from app.services.errors import Forbidden, ServiceError
from tests.conftest import form, login


def make_task(db, people, project="pay", title="Write UAC for refunds", **kwargs) -> Task:
    task = task_service.create_task(db, people["pm"], people[project].id, title, **kwargs)
    db.commit()
    return task


def test_create_task_through_the_form(client, people, db):
    login(client, "asha@test.com")
    response = client.post("/tasks", data=form(client, project_id=people["pay"].id, title="Elicit refund rules",
                                              priority="High", task_type="Requirements", assignee_id=people["asha"].id,
                                              estimate_hours="4", due_date="2030-01-31"), follow_redirects=False)
    assert response.status_code == 303
    task = db.query(Task).one()
    assert task.title == "Elicit refund rules" and task.assignee_id == people["asha"].id
    assert task.status_history[0].to_status == TaskStatus.TODO
    assert client.get(response.headers["location"]).status_code == 200


def test_title_is_required(db, people):
    with pytest.raises(ServiceError):
        task_service.create_task(db, people["pm"], people["pay"].id, "   ")


def test_assignee_must_be_project_member(db, people):
    with pytest.raises(ServiceError, match="not a member"):
        task_service.create_task(db, people["pm"], people["pay"].id, "X", assignee_id=people["ben"].id)


def test_ba_only_sees_tasks_in_own_projects(client, db, people):
    make_task(db, people, "pay", "Payments task")
    crm_task = make_task(db, people, "crm", "Portal task")
    login(client, "asha@test.com")
    page = client.get("/tasks").text
    assert "Payments task" in page and "Portal task" not in page
    assert client.get(f"/tasks/{crm_task.id}").status_code == 403


def test_pm_sees_everything(client, db, people):
    make_task(db, people, "pay", "Payments task")
    make_task(db, people, "crm", "Portal task")
    login(client, "pm@test.com")
    page = client.get("/tasks").text
    assert "Payments task" in page and "Portal task" in page


def test_filters_and_search(db, people):
    make_task(db, people, title="Refund UAC")
    make_task(db, people, title="Chargeback analysis")
    found = task_service.search_tasks(db, people["pm"], task_service.TaskFilters(q="refund"))
    assert [t.title for t in found] == ["Refund UAC"]


def test_status_workflow_and_history(db, people):
    task = make_task(db, people)
    task_service.change_status(db, people["asha"], task, TaskStatus.IN_PROGRESS)
    task_service.change_status(db, people["asha"], task, TaskStatus.IN_REVIEW)
    task_service.change_status(db, people["asha"], task, TaskStatus.DONE)
    db.commit()
    steps = [h.to_status for h in db.query(TaskStatusHistory).filter_by(task_id=task.id).order_by(TaskStatusHistory.id)]
    assert steps == [TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.IN_REVIEW, TaskStatus.DONE]


def test_cannot_skip_workflow_steps(db, people):
    task = make_task(db, people)
    with pytest.raises(ServiceError, match="can't move"):
        task_service.change_status(db, people["asha"], task, TaskStatus.DONE)


def test_htmx_status_change_returns_partial(client, db, people):
    task = make_task(db, people)
    login(client, "asha@test.com")
    response = client.post(f"/tasks/{task.id}/status", data={"status": "In Progress"},
                           headers={"HX-Request": "true", "X-CSRF-Token": client.csrf})
    assert response.status_code == 200
    assert 'id="task-status"' in response.text
    assert "toast" in response.headers["hx-trigger"]
    db.expire_all()
    assert db.get(Task, task.id).status == TaskStatus.IN_PROGRESS


def test_invalid_move_from_board_shows_error_toast(client, db, people):
    task = make_task(db, people)
    login(client, "asha@test.com")
    response = client.post(f"/tasks/{task.id}/status", data={"status": "Done"},
                           headers={"HX-Request": "true", "X-CSRF-Token": client.csrf})
    assert response.headers["hx-reswap"] == "none"
    assert "danger" in response.headers["hx-trigger"]


def test_comments(client, db, people):
    task = make_task(db, people)
    login(client, "asha@test.com")
    response = client.post(f"/tasks/{task.id}/comments", data={"body": "Need sign-off from finance"},
                           headers={"HX-Request": "true", "X-CSRF-Token": client.csrf})
    assert "Need sign-off from finance" in response.text
    comment = db.query(TaskComment).one()
    with pytest.raises(Forbidden):
        task_service.delete_comment(db, people["ben"], comment)


def test_attachment_upload_and_download(client, db, people):
    task = make_task(db, people)
    login(client, "asha@test.com")
    client.post(f"/tasks/{task.id}/attachments", data=form(client),
                files={"file": ("notes.txt", b"workshop notes", "text/plain")})
    db.expire_all()
    attachment = db.get(Task, task.id).attachments[0]
    assert attachment.filename == "notes.txt" and "notes" not in attachment.stored_path.split("/")[-1]
    response = client.get(f"/tasks/{task.id}/attachments/{attachment.id}")
    assert response.content == b"workshop notes"


def test_dangerous_upload_type_is_refused(client, db, people):
    task = make_task(db, people)
    login(client, "asha@test.com")
    client.post(f"/tasks/{task.id}/attachments", data=form(client),
                files={"file": ("run.exe", b"MZ", "application/octet-stream")})
    db.expire_all()
    assert db.get(Task, task.id).attachments == []


def test_board_groups_by_status(client, db, people):
    make_task(db, people, title="Card one")
    login(client, "pm@test.com")
    page = client.get("/board").text
    assert "Card one" in page and 'data-status="In Review"' in page


def test_quick_search(client, db, people):
    make_task(db, people, title="Refund approval flow")
    login(client, "asha@test.com")
    assert "Refund approval flow" in client.get("/tasks-search?q=refund").text


def test_only_creator_or_manager_deletes(db, people):
    task = make_task(db, people)
    with pytest.raises(Forbidden):
        task_service.delete_task(db, people["asha"], task)
