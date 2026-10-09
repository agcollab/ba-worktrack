from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class Status(Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"


@dataclass
class Task:
    title: str
    status: Status = Status.TODO
    hours: float = 0.0
    due: date | None = None                         # "a date, or nothing"
    tags: list[str] = field(default_factory=list)   # a NEW list per task

    def start(self) -> None:                        # -> None: returns nothing
        self.status = Status.IN_PROGRESS

    def is_done(self) -> bool:
        return self.status == Status.DONE

t = Task("Write test cases", tags=["UAT"])
t.start()
print(t.status.value, t.is_done())                  # In Progress False