"""JIRA / ADO item types: kept as is on import, filtered on import, and read-only when an admin says so."""
import httpx
import pytest

from app.integrations import service
from app.integrations.registry import set_test_transport
from app.models import ItemType, Task, TaskStatus
from app.services import item_types as item_type_service
from app.services import tasks as task_service
from app.services.errors import Forbidden
from tests.conftest import form, login
from tests.test_integrations import FakeJira, ado_handler, ado_item


@pytest.fixture
def jira(db, people):
    fake = FakeJira()
    set_test_transport(httpx.MockTransport(fake))
    integration = service.save_integration(
        db, name="Payments JIRA", kind="jira", base_url="https://acme.atlassian.net", remote_project="PAY",
        username="bot@acme.com", token="secret-token", local_project_id=people["pay"].id, config={})
    db.commit()
    yield integration, fake
    set_test_transport(None)


def make_read_only(db, people, name="Story", source="jira"):
    item_type = db.query(ItemType).filter_by(source=source, name=name).one()
    item_type_service.set_read_only(db, people["admin"], item_type, True)
    db.commit()
    return item_type


def test_import_keeps_remote_type_and_id(db, jira):
    integration, _ = jira
    service.import_items(db, integration)
    task = db.query(Task).filter_by(external_id="PAY-1").one()
    assert task.key == "PAY-1"  # the JIRA key, not our own numbering
    assert task.item_type.name == "Story" and task.type_label == "Story"
    assert task.task_type == "Requirements"  # still filed under a category for reports
    assert db.query(ItemType).count() == 1  # one type, shared by both issues


def test_ado_keeps_work_item_type_and_id(db, people):
    state = {7: ado_item(7, "New"), 8: ado_item(8, "Active")}
    set_test_transport(httpx.MockTransport(ado_handler(state)))
    integration = service.save_integration(
        db, name="Portal ADO", kind="ado", base_url="https://dev.azure.com/acme", remote_project="Portal",
        username=None, token="pat", local_project_id=people["crm"].id, config={})
    service.import_items(db, integration)
    seven = db.query(Task).filter_by(external_id="7").one()
    assert seven.key == "7" and seven.type_label == "User Story" and seven.item_type.source == "ado"
    result = service.fetch_item_types(db, integration)
    names = {t.name for t, _ in item_type_service.list_item_types(db, "ado")}
    assert names == {"User Story", "Bug"}  # hidden and disabled types are skipped
    assert result.created == 1
    service.save_item_type_settings(db, integration, people["admin"],
                                    {t.id for t, _ in item_type_service.list_item_types(db, "ado") if t.name == "Bug"}, set())
    service.import_items(db, integration)
    assert "[System.WorkItemType] IN ('Bug')" in state["wiql"]
    set_test_transport(None)


def test_fetch_item_types_and_filter_import(db, people, jira):
    integration, fake = jira
    result = service.fetch_item_types(db, integration)
    assert result.created == 3
    story = db.query(ItemType).filter_by(name="Story").one()
    assert story.description == "A user story" and not story.is_read_only
    bug = db.query(ItemType).filter_by(name="Bug").one()
    service.save_item_type_settings(db, integration, people["admin"], {story.id, bug.id}, {bug.id})
    assert integration.config["import_types"] == ["Bug", "Story"] and bug.is_read_only
    service.import_items(db, integration)
    assert fake.jql[-1] == '(project = "PAY") AND issuetype in ("Bug", "Story") ORDER BY updated DESC'


def test_custom_jql_gets_type_filter():
    from app.integrations.jira import JiraConnector
    connector = JiraConnector("https://acme.atlassian.net", "PAY", "t", "a@b.c",
                              config={"jql": "labels = BA order by created", "import_types": ['Spike "x"']})
    assert connector._jql() == '(labels = BA) AND issuetype in ("Spike \\"x\\"") order by created'


def test_read_only_type_blocks_local_changes(db, people, jira):
    integration, _ = jira
    service.import_items(db, integration)
    make_read_only(db, people)
    task = db.query(Task).filter_by(external_id="PAY-1").one()
    assert task.is_read_only and not task_service.can_edit(people["admin"], task)
    assert task_service.allowed_next(task) == []
    with pytest.raises(Forbidden, match="read-only"):
        task_service.change_status(db, people["admin"], task, TaskStatus.IN_PROGRESS)
    with pytest.raises(Forbidden, match="read-only"):
        task_service.update_task(db, people["admin"], task, "New title", None, task.priority, task.task_type,
                                 None, None, None)
    with pytest.raises(Forbidden, match="read-only"):
        task_service.delete_task(db, people["admin"], task)
    # Tracking still works: comments and time
    task_service.add_comment(db, people["asha"], task, "Investigating")


def test_read_only_still_follows_remote_changes(db, people, jira):
    integration, fake = jira
    service.import_items(db, integration)
    make_read_only(db, people)
    fake.issues["PAY-1"]["fields"]["status"] = {"name": "Done", "statusCategory": {"key": "done"}}
    fake.issues["PAY-1"]["fields"]["summary"] = "Renamed in JIRA"
    service.import_items(db, integration)
    task = db.query(Task).filter_by(external_id="PAY-1").one()
    assert task.status == TaskStatus.DONE and task.title == "Renamed in JIRA"


def test_read_only_in_the_web_ui(client, db, people, jira):
    integration, _ = jira
    service.import_items(db, integration)
    make_read_only(db, people)
    task = db.query(Task).filter_by(external_id="PAY-1").one()
    login(client, "asha@test.com")
    page = client.get(f"/tasks/{task.id}").text
    assert "Read-only" in page and f"/tasks/{task.id}/edit" not in page and "Delete task" not in page
    assert client.get(f"/tasks/{task.id}/edit", follow_redirects=False).status_code in (303, 400, 403)
    moved = client.post(f"/tasks/{task.id}/status", data=form(client, status="In Progress"),
                        headers={"HX-Request": "true"})
    assert "read-only" in moved.headers.get("HX-Trigger", "")
    db.refresh(task)
    assert task.status == TaskStatus.TODO
    board = client.get("/board").text
    assert "is-locked" in board
    api = client.patch(f"/api/v1/tasks/{task.id}", json={"title": "x"})
    assert api.status_code == 403


def test_admin_toggles_item_type(client, db, people, jira):
    integration, _ = jira
    service.import_items(db, integration)
    story = db.query(ItemType).filter_by(name="Story").one()
    login(client, "asha@test.com")
    assert client.get("/admin/item-types").status_code == 403
    login(client, "admin@test.com")
    page = client.get("/admin/item-types").text
    assert "Story" in page and "Editable" in page
    response = client.post(f"/admin/item-types/{story.id}", data=form(client, read_only=["0", "1"]),
                           follow_redirects=False)
    assert response.status_code == 303
    db.refresh(story)
    assert story.is_read_only
    client.post(f"/admin/item-types/{story.id}", data=form(client, read_only="0"))
    db.refresh(story)
    assert not story.is_read_only
    page = client.get(f"/integrations/{integration.id}").text
    assert "Item types" in page and "Save item types" in page
