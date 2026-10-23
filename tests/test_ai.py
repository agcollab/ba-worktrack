"""AI Studio with a fake model: validation, retries, logging, saving, offline handling."""
import json

import pytest

from app.ai import studio
from app.ai.provider import AIUnavailable, FakeProvider, set_provider
from app.models import AIGenerationLog, Requirement
from app.services import tasks as task_service
from app.services.errors import ServiceError
from tests.conftest import form, login

SOURCE = "Customers can request a refund within 30 days; refunds over 500 need a supervisor."
UAC = json.dumps({"criteria": [
    {"given": "a paid order from 10 days ago", "when": "the customer requests a refund", "then": "a refund is created"},
    {"given": "a refund of 600", "when": "it is submitted", "then": "it waits for supervisor approval"}]})


@pytest.fixture
def task(db, people):
    t = task_service.create_task(db, people["pm"], people["pay"].id, "Refund UAC")
    db.commit()
    return t


def test_valid_output_is_parsed_and_logged(db, people, task):
    set_provider(FakeProvider([UAC]))
    output, log = studio.generate(db, people["asha"], "uac", SOURCE, task)
    assert len(output.criteria) == 2
    assert log.success and log.prompt_version == "v1" and log.model_name == "fake-model"


def test_invalid_output_is_retried(db, people, task):
    fake = FakeProvider(["not json at all", '```json\n' + UAC + '\n```'])
    set_provider(fake)
    output, log = studio.generate(db, people["asha"], "uac", SOURCE, task)
    assert len(fake.calls) == 2 and "previous answer was invalid" in fake.calls[1][1]
    assert output.criteria[1].then == "it waits for supervisor approval"


def test_gives_up_after_three_bad_answers(db, people, task):
    set_provider(FakeProvider(["{}", "{}", "{}"]))
    with pytest.raises(ServiceError, match="expected format"):
        studio.generate(db, people["asha"], "uac", SOURCE, task)
    log = db.query(AIGenerationLog).one()
    assert not log.success and "Invalid output" in log.error_message


def test_model_offline_is_reported_not_crashed(client, db, people, task):
    class Down:
        model_name = "down"

        def complete_json(self, *args, **kwargs):
            raise AIUnavailable("Ollama is not running")

    set_provider(Down())
    login(client, "asha@test.com")
    response = client.post("/ai/generate", data=form(client, feature="uac", source_text=SOURCE, task_id=task.id),
                           headers={"HX-Request": "true"})
    assert response.status_code == 200 and "Ollama is not running" in response.text
    assert db.query(AIGenerationLog).one().success is False


def test_generate_review_and_save(client, db, people, task):
    set_provider(FakeProvider([UAC]))
    login(client, "asha@test.com")
    page = client.post("/ai/generate", data=form(client, feature="uac", source_text=SOURCE, task_id=task.id),
                       headers={"HX-Request": "true"}).text
    assert "a refund is created" in page
    log = db.query(AIGenerationLog).one()
    response = client.post("/ai/save", data=form(
        client, log_id=log.id, task_id=task.id, requirement_title="Refund rules",
        **{"items-0-keep": "1", "items-0-given": "a paid order from 10 days ago",
           "items-0-when": "the customer requests a refund", "items-0-then": "a refund is created (edited)",
           "items-1-given": "x", "items-1-when": "y", "items-1-then": "dropped"}), follow_redirects=False)
    assert response.status_code == 303
    requirement = db.query(Requirement).one()
    assert requirement.source == "AI" and requirement.task_id == task.id
    assert [c.then_text for c in requirement.criteria] == ["a refund is created (edited)"]
    db.expire_all()
    assert db.get(AIGenerationLog, log.id).outcome == "edited"


def test_short_input_is_refused(db, people):
    set_provider(FakeProvider([UAC]))
    with pytest.raises(ServiceError):
        studio.generate(db, people["asha"], "uac", "too short")


def test_test_case_steps_accept_text_or_list(db, people, task):
    answer = json.dumps({"test_cases": [{"title": "Refund under 500", "preconditions": "Paid order",
                                         "steps": "Open order\nRequest refund", "expected_result": "Refund created",
                                         "priority": "high"}]})
    set_provider(FakeProvider([answer]))
    output, _ = studio.generate(db, people["asha"], "test_cases", SOURCE, task)
    assert output.test_cases[0].steps == ["Open order", "Request refund"]
    assert output.test_cases[0].priority == "High"
