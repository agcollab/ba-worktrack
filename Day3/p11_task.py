"""P11: Task as a dataclass with enums, plus JSON save/load (P9)."""
import json
from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path


class Status(str, Enum):
    TODO = "To Do"
    IN_PROGRESS = "In Progress"
    DONE = "Done"


class Priority(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"


@dataclass
class Task:
    title: str
    assignee: str
    status: Status = Status.TODO
    priority: Priority = Priority.MEDIUM
    hours: float = 0.0
    due: date | None = None

    # ---------- behaviour (same rules as P10) ----------
    def start(self) -> None:
        self.status = Status.IN_PROGRESS

    def complete(self) -> None:
        if self.status != Status.IN_PROGRESS:
            raise ValueError("Only an In Progress task can be completed")
        self.status = Status.DONE

    def log_hours(self, h: float) -> None:
        if h <= 0:
            raise ValueError("Hours must be positive")
        self.hours += h

    # ---------- converting to / from plain data ----------
    def to_dict(self) -> dict:
        """Turn the task into a dict that json can save (only str/number/None)."""
        return {
            "title": self.title,
            "assignee": self.assignee,
            "status": self.status.value,          # Status.DONE -> "Done"
            "priority": self.priority.value,      # Priority.HIGH -> "High"
            "hours": self.hours,
            "due": self.due.isoformat() if self.due else None,  # date -> "2026-10-20"
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        """Build a Task back from a dict made by to_dict()."""
        return cls(
            title=data["title"],
            assignee=data["assignee"],
            status=Status(data["status"]),        # "Done" -> Status.DONE
            priority=Priority(data["priority"]),
            hours=data["hours"],
            due=date.fromisoformat(data["due"]) if data["due"] else None,
        )


# ---------- saving / loading many tasks ----------
def save_tasks(tasks: list[Task], path: Path) -> None:
    data = [t.to_dict() for t in tasks]
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_tasks(path: Path) -> list[Task]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Task.from_dict(d) for d in data]


if __name__ == "__main__":
    # Exercise 1: build tasks with the dataclass
    t1 = Task("Draft BRD", "Ankur", priority=Priority.HIGH, due=date(2026, 10, 20))
    t1.start()
    t1.log_hours(3.5)

    t2 = Task("Write UAC for login", "Priya")
    t2.start()
    t2.log_hours(2)
    t2.complete()

    t3 = Task("Prepare UAT test cases", "Rahul", priority=Priority.LOW)

    tasks = [t1, t2, t3]

    # Exercise 2: save to JSON and load back
    path = Path(__file__).parent / "tasks.json"
    save_tasks(tasks, path)
    print(f"Saved {len(tasks)} tasks to {path.name}")

    loaded = load_tasks(path)
    for t in loaded:
        print(t)

    # Proof: dataclasses compare field by field, so this is True only if nothing was lost
    print("Round trip OK:", loaded == tasks)
    print("Type of due after loading:", type(loaded[0].due).__name__)
    print("Type of status after loading:", type(loaded[0].status).__name__)