"""A6: a mini task API with FastAPI (data kept in memory, lost on restart).

Run (from crash-course/api):  uvicorn mini_api:app --reload
Then open:                    http://127.0.0.1:8000/docs
"""
from itertools import count
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

Status = Literal["To Do", "In Progress", "Done"]   # only these 3 values are accepted


# ---------- Pydantic schemas: the shape of data going in and out ----------
class TaskIn(BaseModel):
    """What the client sends to create a task."""
    title: str = Field(min_length=1, max_length=200)
    status: Status = "To Do"
    hours: float = Field(default=0, ge=0)            # ge=0: greater than or equal to 0


class TaskUpdate(BaseModel):
    """What the client sends to change a task. Every field is optional."""
    title: str | None = Field(default=None, min_length=1, max_length=200)
    status: Status | None = None
    hours: float | None = Field(default=None, ge=0)


class TaskOut(TaskIn):
    """What the API sends back: everything in TaskIn plus the id."""
    id: int


# ---------- "database" (a dict in memory) ----------
app = FastAPI(title="Mini Task API")
tasks: dict[int, TaskOut] = {}
_ids = count(1)        # 1, 2, 3, ... never reuses an id, even after a delete


def reset_db() -> None:
    """Empty the store. Used by the tests so each test starts clean."""
    global _ids
    tasks.clear()
    _ids = count(1)


def get_or_404(task_id: int) -> TaskOut:
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return tasks[task_id]


# ---------- routes: one function per method + URL ----------
@app.get("/tasks", response_model=list[TaskOut])
def list_tasks(status: Status | None = None):
    """GET /tasks  or  GET /tasks?status=Done   (status is a QUERY parameter)."""
    result = list(tasks.values())
    if status:
        result = [t for t in result if t.status == status]
    return result


@app.post("/tasks", response_model=TaskOut, status_code=201)
def create_task(task: TaskIn):
    """POST /tasks with a JSON body -> 201 Created."""
    new = TaskOut(id=next(_ids), **task.model_dump())
    tasks[new.id] = new
    return new


@app.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: int):
    """GET /tasks/3   (task_id is a PATH parameter; FastAPI converts it to int)."""
    return get_or_404(task_id)


@app.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: int, changes: TaskUpdate):
    """PATCH /tasks/3 with only the fields to change, e.g. {"status": "Done"}."""
    task = get_or_404(task_id)
    data = changes.model_dump(exclude_unset=True, exclude_none=True)  # only what was sent
    updated = task.model_copy(update=data)
    tasks[task_id] = updated
    return updated


@app.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: int):
    """DELETE /tasks/3 -> 204 No Content (success, nothing to send back)."""
    get_or_404(task_id)
    del tasks[task_id]
