"""AI Studio: generate requirements, UAC or test cases, validate them, log the call,
and save what the BA approved."""
import json
import time
from pathlib import Path

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.ai.provider import AIUnavailable, get_provider
from app.ai.schemas import FEATURES
from app.models import AIGenerationLog, Requirement, Task, User
from app.services import requirements as requirement_service
from app.services.errors import ServiceError

PROMPT_DIR = Path(__file__).parent / "prompts"
PROMPT_VERSION = "v1"
MAX_ATTEMPTS = 3
MAX_INPUT_CHARS = 8000


def load_prompt(feature: str, version: str = PROMPT_VERSION) -> str:
    return (PROMPT_DIR / f"{feature}.{version}.txt").read_text(encoding="utf-8")


def _extract_json(text: str) -> str:
    """Models sometimes wrap JSON in ``` fences or add a sentence; keep the object."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):] if "{" in text else text
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start != -1 and end > start else text


def generate(db: Session, user: User, feature: str, source_text: str, task: Task | None = None) -> tuple[BaseModel, AIGenerationLog]:
    if feature not in FEATURES:
        raise ServiceError("Unknown AI feature.")
    source_text = (source_text or "").strip()
    if len(source_text) < 20:
        raise ServiceError("Describe the need in at least a sentence or two (20+ characters).")
    if len(source_text) > MAX_INPUT_CHARS:
        raise ServiceError(f"Input is too long ({MAX_INPUT_CHARS} characters max).")
    _, schema = FEATURES[feature]
    system = load_prompt(feature)
    context = f"Task: {task.title}\n{task.description or ''}\n\n" if task else ""
    user_prompt = f"{context}Input:\n{source_text}"

    provider = get_provider()
    log = AIGenerationLog(user_id=user.id, task_id=task.id if task else None, feature=feature,
                          model_name=provider.model_name, prompt_version=PROMPT_VERSION, prompt=user_prompt)
    db.add(log)
    started = time.perf_counter()
    raw, last_error = "", ""
    try:
        for _attempt in range(MAX_ATTEMPTS):
            prompt = user_prompt if not last_error else (
                f"{user_prompt}\n\nYour previous answer was invalid: {last_error}\nReturn corrected JSON only.")
            raw = provider.complete_json(system, prompt, schema.model_json_schema())
            try:
                parsed = schema.model_validate_json(_extract_json(raw))
            except ValidationError as exc:
                last_error = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:5])
                continue
            log.response, log.success = parsed.model_dump_json(), True
            return parsed, log
        log.success, log.response = False, raw[:20000]
        log.error_message = f"Invalid output after {MAX_ATTEMPTS} attempts: {last_error}"
        raise ServiceError("The model's answer wasn't in the expected format, even after retrying. "
                           "Try again or rephrase the input.")
    except AIUnavailable as exc:
        log.success, log.error_message = False, str(exc)
        raise
    finally:
        log.duration_ms = int((time.perf_counter() - started) * 1000)
        db.flush()


def save_generation(db: Session, user: User, log: AIGenerationLog, feature: str, items: list[dict],
                    project_id: int, task_id: int | None, requirement_id: int | None,
                    requirement_title: str | None) -> list[Requirement]:
    """Save the reviewed items. Marks the log accepted (unchanged) or edited."""
    if not items:
        raise ServiceError("Select at least one item to save.")
    original = json.loads(log.response or "{}")
    original_items = next(iter(original.values()), []) if original else []
    log.outcome = "accepted" if _same(original_items, items) else "edited"
    saved: list[Requirement] = []
    if feature == "requirements":
        for item in items:
            saved.append(requirement_service.save_requirement(
                db, user, project_id, item["title"], item.get("description"), kind=item.get("kind", "Functional"),
                task_id=task_id, source="AI"))
        return saved
    if requirement_id:
        requirement = requirement_service.get_requirement(db, user, requirement_id)
    else:
        title = (requirement_title or "").strip() or ("Acceptance criteria" if feature == "uac" else "Test cases")
        requirement = requirement_service.save_requirement(db, user, project_id, title, None, task_id=task_id,
                                                           source="AI")
    for item in items:
        if feature == "uac":
            requirement_service.add_criterion(db, requirement, item.get("given"), item.get("when"), item["then"])
        else:
            steps = item["steps"] if isinstance(item["steps"], str) else "\n".join(item["steps"])
            requirement_service.add_test_case(db, requirement, item["title"], steps, item["expected_result"],
                                              item.get("preconditions"), item.get("priority", "Medium"))
    return [requirement]


def reject(log: AIGenerationLog) -> None:
    log.outcome = "rejected"


def _same(original: list[dict], edited: list[dict]) -> bool:
    def norm(items):
        out = []
        for item in items:
            clean = {}
            for k, v in item.items():
                if isinstance(v, list):
                    v = "\n".join(v)
                clean[k] = (v or "").strip() if isinstance(v, str) else v
            out.append(clean)
        return out
    return norm(original) == norm(edited)
