"""JIRA and Azure DevOps connectors with mocked HTTP (no internet needed)."""
import json

import httpx
import pytest

from app.integrations import service
from app.integrations.base import ConnectorError
from app.integrations.jira import JiraConnector, adf_to_text
from app.integrations.registry import set_test_transport
from app.models import Integration, SyncLog, Task, TaskStatus
from app.security import decrypt_secret
from app.services import requirements as requirement_service
from app.services import tasks as task_service
from tests.conftest import form, login


def jira_issue(key, status, category="new", summary=None, priority="High", email=None):
    return {"key": key, "fields": {
        "summary": summary or f"Issue {key}", "status": {"name": status, "statusCategory": {"key": category}},
        "priority": {"name": priority}, "issuetype": {"name": "Story"}, "duedate": "2030-01-15",
        "assignee": {"emailAddress": email} if email else None, "updated": "2026-10-20T10:00:00.000+0000",
        "description": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Body"}]}]},
        "timeoriginalestimate": 7200}}


class FakeJira:
    """Just enough of the Jira Cloud REST API for the connector."""

    def __init__(self):
        self.issues = {"PAY-1": jira_issue("PAY-1", "To Do", email="asha@test.com"),
                       "PAY-2": jira_issue("PAY-2", "In Progress", "indeterminate")}
        self.comments: list[dict] = []
        self.transitions: list[str] = []
        self.created = 0
        self.jql: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        if path.endswith("/myself"):
            return httpx.Response(200, json={"displayName": "Bot"})
        if "/project/" in path:
            return httpx.Response(200, json={"key": "PAY", "name": "Payments", "issueTypes": [
                {"name": "Story", "description": "A user story"}, {"name": "Bug"}, {"name": "Epic"}]})
        if path.endswith("/search/jql"):
            body = json.loads(request.content)
            self.jql.append(body["jql"])
            keys = list(self.issues)
            if body["jql"].startswith("key in"):
                keys = [k for k in keys if f'"{k}"' in body["jql"]]
            return httpx.Response(200, json={"issues": [self.issues[k] for k in keys], "isLast": True})
        if path.endswith("/transitions") and method == "GET":
            return httpx.Response(200, json={"transitions": [
                {"id": str(i), "name": n, "to": {"name": n}} for i, n in enumerate(["To Do", "In Progress", "In Review", "Done"])]})
        if path.endswith("/transitions") and method == "POST":
            key = path.split("/")[-2]
            name = ["To Do", "In Progress", "In Review", "Done"][int(json.loads(request.content)["transition"]["id"])]
            self.issues[key]["fields"]["status"]["name"] = name
            self.transitions.append(f"{key}:{name}")
            return httpx.Response(204)
        if path.endswith("/comment"):
            self.comments.append(json.loads(request.content))
            return httpx.Response(201, json={"id": "1"})
        if path.endswith("/issue") and method == "POST":
            self.created += 1
            key = f"PAY-{100 + self.created}"
            self.issues[key] = jira_issue(key, "To Do", summary=json.loads(request.content)["fields"]["summary"])
            return httpx.Response(201, json={"key": key})
        return httpx.Response(404)


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


def test_token_is_encrypted(db, jira):
    integration, _ = jira
    assert "secret-token" not in integration.encrypted_token
    assert decrypt_secret(integration.encrypted_token) == "secret-token"


def test_test_connection(db, jira):
    ok, message = service.test_connection(db, jira[0])
    assert ok and "Bot" in message


def test_import_creates_tasks_with_mapped_fields(db, people, jira):
    integration, _ = jira
    result = service.import_items(db, integration)
    db.commit()
    assert result.created == 2 and result.status == "ok"
    t1 = db.query(Task).filter_by(external_id="PAY-1").one()
    assert t1.status == TaskStatus.TODO and t1.assignee_id == people["asha"].id
    assert t1.priority == "High" and t1.estimate_hours == 2 and t1.description == "Body"
    assert t1.external_url == "https://acme.atlassian.net/browse/PAY-1"
    assert db.query(Task).filter_by(external_id="PAY-2").one().status == TaskStatus.IN_PROGRESS
    again = service.import_items(db, integration)
    assert again.created == 0  # no duplicates


def test_remote_status_change_is_pulled(db, jira):
    integration, fake = jira
    service.import_items(db, integration)
    fake.issues["PAY-1"]["fields"]["status"] = {"name": "In Progress", "statusCategory": {"key": "indeterminate"}}
    result = service.sync_statuses(db, integration)
    assert result.updated == 1
    assert db.query(Task).filter_by(external_id="PAY-1").one().status == TaskStatus.IN_PROGRESS


def test_local_status_change_is_pushed(db, people, jira):
    integration, fake = jira
    service.import_items(db, integration)
    task = db.query(Task).filter_by(external_id="PAY-1").one()
    task_service.change_status(db, people["asha"], task, TaskStatus.IN_PROGRESS)
    result = service.sync_statuses(db, integration)
    assert result.pushed == 1 and fake.transitions == ["PAY-1:In Progress"]


def test_conflict_is_logged_and_remote_wins(db, people, jira):
    integration, fake = jira
    service.import_items(db, integration)
    task = db.query(Task).filter_by(external_id="PAY-1").one()
    task_service.change_status(db, people["asha"], task, TaskStatus.IN_PROGRESS)
    fake.issues["PAY-1"]["fields"]["status"] = {"name": "Done", "statusCategory": {"key": "done"}}
    result = service.sync_statuses(db, integration)
    db.commit()
    assert len(result.conflicts) == 1 and task.status == TaskStatus.DONE
    log = db.query(SyncLog).filter_by(action="sync").one()
    assert log.conflicts == 1 and "PAY-1" in log.message


def test_push_task_and_requirements(db, people, jira):
    integration, fake = jira
    task = task_service.create_task(db, people["pm"], people["pay"].id, "Local task")
    item = service.push_task(db, integration, task, people["pm"])
    assert task.external_id == item.external_id == "PAY-101"
    req = requirement_service.save_requirement(db, people["pm"], people["pay"].id, "Refund approval", None, task_id=task.id)
    requirement_service.add_criterion(db, req, "a refund", "submitted", "it is pending")
    requirement_service.add_test_case(db, req, "Pending check", "Submit\nCheck", "Pending")
    assert service.push_requirements(db, task, people["pm"]) == 1
    text = adf_to_text(fake.comments[0]["body"])
    assert "Given a refund When submitted Then it is pending" in text and "Pending check" in text


def test_bad_credentials_give_a_clear_error(db, people):
    set_test_transport(httpx.MockTransport(lambda r: httpx.Response(401)))
    integration = service.save_integration(
        db, name="Bad", kind="jira", base_url="https://acme.atlassian.net", remote_project="PAY",
        username="x@acme.com", token="wrong", local_project_id=people["pay"].id, config={})
    ok, message = service.test_connection(db, integration)
    assert not ok and "refused the credentials" in message


def test_rate_limit_is_retried():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(200, json={"displayName": "Bot"})

    connector = JiraConnector("https://acme.atlassian.net", "PAY", "t", "a@b.c",
                              transport=httpx.MockTransport(handler), sleep=lambda s: None)
    assert connector.request("GET", "/rest/api/3/myself").json()["displayName"] == "Bot"
    assert calls["n"] == 3


def test_retries_give_up(monkeypatch):
    connector = JiraConnector("https://acme.atlassian.net", "PAY", "t", "a@b.c",
                              transport=httpx.MockTransport(lambda r: httpx.Response(503)), sleep=lambda s: None)
    with pytest.raises(ConnectorError, match="503"):
        connector.request("GET", "/rest/api/3/myself")


# ---- Azure DevOps --------------------------------------------------------------

def ado_handler(state):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        assert request.headers["authorization"].startswith("Basic ")
        if path.endswith("/_apis/wit/wiql"):
            state["wiql"] = json.loads(request.content)["query"]
            return httpx.Response(200, json={"workItems": [{"id": 7}, {"id": 8}]})
        if path.endswith("/workitemsbatch"):
            ids = json.loads(request.content)["ids"]
            return httpx.Response(200, json={"value": [state[i] for i in ids]})
        if "/_apis/wit/workitems/" in path and request.method == "PATCH":
            wid = int(path.split("/")[-1])
            state[wid]["fields"]["System.State"] = json.loads(request.content)[0]["value"]
            return httpx.Response(200, json=state[wid])
        if path.endswith("/comments"):
            state["comments"] = json.loads(request.content)["text"]
            return httpx.Response(200, json={})
        if path.endswith("/_apis/wit/workitemtypes"):
            return httpx.Response(200, json={"value": [{"name": "User Story"}, {"name": "Bug"},
                                                       {"name": "Code Review Request"}, {"name": "Old", "isDisabled": True}]})
        if path.endswith("/_apis/wit/workitemtypecategories"):
            return httpx.Response(200, json={"value": [{"referenceName": "Microsoft.HiddenCategory",
                                                        "workItemTypes": [{"name": "Code Review Request"}]}]})
        if "/_apis/projects/" in path:
            return httpx.Response(200, json={"name": "Portal", "state": "wellFormed"})
        return httpx.Response(404)
    return handler


def ado_item(wid, state, email=None):
    return {"id": wid, "fields": {"System.Title": f"Story {wid}", "System.State": state,
                                  "System.WorkItemType": "User Story", "Microsoft.VSTS.Common.Priority": 1,
                                  "System.Description": "<div>Line one<br>Line two</div>",
                                  "System.AssignedTo": {"uniqueName": email} if email else None}}


def test_ado_import_and_sync(db, people):
    state = {7: ado_item(7, "New", "ben@test.com"), 8: ado_item(8, "Active")}
    set_test_transport(httpx.MockTransport(ado_handler(state)))
    integration = service.save_integration(
        db, name="Portal ADO", kind="ado", base_url="https://dev.azure.com/acme", remote_project="Portal",
        username=None, token="pat", local_project_id=people["crm"].id, config={})
    assert service.test_connection(db, integration)[0]
    result = service.import_items(db, integration)
    assert result.created == 2
    seven = db.query(Task).filter_by(external_id="7").one()
    assert seven.status == TaskStatus.TODO and seven.priority == "Critical" and seven.assignee_id == people["ben"].id
    assert seven.description == "Line one\nLine two" and seven.task_type == "Requirements"
    assert db.query(Task).filter_by(external_id="8").one().status == TaskStatus.IN_PROGRESS
    task_service.change_status(db, people["ben"], seven, TaskStatus.IN_PROGRESS)
    service.sync_statuses(db, integration)
    assert state[7]["fields"]["System.State"] == "Active"  # default Agile mapping


def test_integration_admin_pages(client, db, people):
    set_test_transport(httpx.MockTransport(FakeJira()))
    login(client, "admin@test.com")
    response = client.post("/integrations", data=form(
        client, kind="jira", name="UI JIRA", base_url="https://acme.atlassian.net", remote_project="PAY",
        username="bot@acme.com", token="zz-plain-token-zz", local_project_id=people["pay"].id, deployment="cloud",
        conflict_policy="local_wins", max_items="50", is_enabled="1"), follow_redirects=False)
    assert response.status_code == 303
    integration = db.query(Integration).one()
    assert integration.config["conflict_policy"] == "local_wins" and integration.config["max_items"] == 50
    client.post(f"/integrations/{integration.id}/import", data=form(client))
    assert db.query(Task).filter_by(integration_id=integration.id).count() == 2
    page = client.get(f"/integrations/{integration.id}").text
    assert "Sync log" in page and "zz-plain-token-zz" not in page


def test_comments_are_signed_with_the_app_name(monkeypatch):
    from app.config import settings
    from app.integrations.jira import text_to_adf, text_to_wiki

    monkeypatch.setattr(settings, "APP_NAME", "AnalystHub")
    assert text_to_wiki("Heading", [("Block", ["line"])]).endswith("_Posted from AnalystHub_")
    assert text_to_adf("Heading", [])["content"][-1]["content"][0]["text"] == "Posted from AnalystHub"
