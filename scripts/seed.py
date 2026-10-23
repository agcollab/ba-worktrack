"""Fill the database with realistic demo data.

Run from the repository root, after "alembic upgrade head":
    python -m scripts.seed            # only works on an empty database
    python -m scripts.seed --reset    # wipe every table first, then seed again

Creates: 3 roles, 7 users (1 Admin, 2 PMs, 4 BAs), 2 projects, 50 tasks with
status history, 200 time entries spread over the last 6 weeks, and sample
requirements with acceptance criteria and test cases.
Every demo user's password is "Passw0rd!".

The random numbers use a fixed seed (42), so you get the same data each run.
"""
import argparse
import random
from datetime import date, datetime, time, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.database import Base, SessionLocal
from app.models import (
    AcceptanceCriterion,
    Project,
    ProjectMember,
    Requirement,
    Role,
    Task,
    TaskPriority,
    TaskStatus,
    TaskStatusHistory,
    TaskType,
    TestCase,
    TimeEntry,
    User,
)
from app.security import hash_password

DEMO_PASSWORD = "Passw0rd!"
TASK_COUNT = 50
TIME_ENTRY_COUNT = 200
WEEKS_OF_HISTORY = 6
MAX_HOURS_PER_DAY = 9.0

ROLES = {
    "Admin": "Manages users, roles and integrations",
    "PM": "Sees metrics and weekly reports for their projects",
    "BA": "Creates tasks, logs hours, generates requirements with AI",
}

# (email, full name, role)
USERS = [
    ("admin@demo.com", "Demo Admin", "Admin"),
    ("priya.pm@demo.com", "Priya Sharma", "PM"),
    ("mark.pm@demo.com", "Mark Ellis", "PM"),
    ("asha.ba@demo.com", "Asha Rao", "BA"),
    ("ben.ba@demo.com", "Ben Carter", "BA"),
    ("chen.ba@demo.com", "Chen Li", "BA"),
    ("dana.ba@demo.com", "Dana Okafor", "BA"),
]

# key, name, description, PM email, BA emails, features the BAs work on
PROJECTS = [
    (
        "PAY",
        "Payments Modernisation",
        "Replace the legacy card and bank payment flows with a new payments platform.",
        "priya.pm@demo.com",
        ["asha.ba@demo.com", "ben.ba@demo.com"],
        ["card checkout", "refunds", "chargebacks", "payment reconciliation",
         "fraud alerts", "invoicing", "direct debit", "merchant payouts"],
    ),
    (
        "CRM",
        "Customer Portal Revamp",
        "A self-service portal where customers manage their account, orders and support cases.",
        "mark.pm@demo.com",
        ["chen.ba@demo.com", "dana.ba@demo.com", "ben.ba@demo.com"],
        ["customer login", "profile management", "support tickets", "live chat",
         "order history", "email notifications", "loyalty points", "address book"],
    ),
]

# Title patterns per task type; {f} is replaced by a feature name
TITLE_PATTERNS = {
    TaskType.REQUIREMENTS: ["Draft BRD section: {f}", "Write user stories: {f}", "Elicit requirements: {f}"],
    TaskType.UAC: ["Write UAC for {f}", "Review acceptance criteria: {f}"],
    TaskType.TESTING: ["Write UAT test cases: {f}", "Run UAT session: {f}", "Triage UAT defects: {f}"],
    TaskType.MEETING: ["Stakeholder workshop: {f}", "Backlog refinement: {f}", "Business demo: {f}"],
    TaskType.ANALYSIS: ["Gap analysis: {f}", "As-is / to-be process map: {f}", "Data mapping: {f}",
                        "Impact analysis: {f}"],
    TaskType.OTHER: ["Update traceability matrix: {f}", "Prepare release notes: {f}"],
}

TIME_NOTES = [
    "Drafted first version", "Updated after review comments", "Call with product owner",
    "Clarified edge cases with dev team", "Walkthrough with QA", "Reworked after workshop",
    None, None,  # some entries have no note
]

# The order a task moves through its statuses
STATUS_FLOW = [TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.IN_REVIEW, TaskStatus.DONE]


def reset_database(db: Session) -> None:
    """Delete every row from every table (children first, so foreign keys are happy)."""
    for table in reversed(Base.metadata.sorted_tables):
        db.execute(delete(table))
    db.commit()


def previous_weekdays(today: date, days_back: int) -> list[date]:
    """Every Monday-Friday from (today - days_back) up to today."""
    start = today - timedelta(days=days_back)
    all_days = (start + timedelta(days=n) for n in range(days_back + 1))
    return [d for d in all_days if d.weekday() < 5]  # weekday(): Mon=0 ... Sun=6


def create_roles_and_users(db: Session) -> dict[str, User]:
    roles = {name: Role(name=name, description=desc) for name, desc in ROLES.items()}
    db.add_all(roles.values())

    users: dict[str, User] = {}
    for email, full_name, role_name in USERS:
        user = User(
            email=email,
            full_name=full_name,
            hashed_password=hash_password(DEMO_PASSWORD),  # a new salt each time
            roles=[roles[role_name]],
        )
        users[email] = user
    db.add_all(users.values())
    return users


def create_projects(db: Session, users: dict[str, User], today: date) -> list[tuple[Project, list[User], list[str]]]:
    """Returns (project, its BAs, its features) for each project."""
    result = []
    for key, name, description, pm_email, ba_emails, features in PROJECTS:
        pm = users[pm_email]
        bas = [users[email] for email in ba_emails]
        project = Project(
            key=key,
            name=name,
            description=description,
            owner=pm,
            start_date=today - timedelta(weeks=WEEKS_OF_HISTORY + 2),
            end_date=today + timedelta(weeks=10),
        )
        project.members = [ProjectMember(user=pm, role_in_project="PM")]
        project.members += [ProjectMember(user=ba, role_in_project="BA") for ba in bas]
        db.add(project)
        result.append((project, bas, features))
    return result


def create_tasks(db: Session, rng: random.Random, projects, today: date) -> list[Task]:
    now = datetime.combine(today, time(17, 0))
    statuses = [TaskStatus.DONE, TaskStatus.IN_PROGRESS, TaskStatus.IN_REVIEW, TaskStatus.TODO]
    status_weights = [35, 25, 15, 25]  # percent of tasks in each status
    priorities = list(TaskPriority)
    priority_weights = [20, 45, 28, 7]

    tasks: list[Task] = []
    used_titles: set[str] = set()
    while len(tasks) < TASK_COUNT:
        project, bas, features = projects[len(tasks) % len(projects)]  # alternate projects
        task_type = rng.choice(list(TaskType))
        title = rng.choice(TITLE_PATTERNS[task_type]).format(f=rng.choice(features))
        if title in used_titles:
            continue  # try again so every title is unique
        used_titles.add(title)

        created_at = now - timedelta(days=rng.randint(3, WEEKS_OF_HISTORY * 7 + 5), hours=rng.randint(0, 8))
        status = rng.choices(statuses, weights=status_weights)[0]
        task = Task(
            project=project,
            title=title,
            description=f"{title} for the {project.name} project.",
            task_type=task_type,
            status=status,
            priority=rng.choices(priorities, weights=priority_weights)[0],
            estimate_hours=rng.choice([2, 3, 4, 6, 8, 12, 16]),
            due_date=created_at.date() + timedelta(days=rng.randint(5, 25)),
            # about 1 task in 15 has nobody assigned yet
            assignee=None if rng.random() < 0.07 else rng.choice(bas),
            created_by=project.owner,
            created_at=created_at,
            updated_at=created_at,
        )
        add_status_history(rng, task, created_at, now)
        tasks.append(task)

    db.add_all(tasks)
    return tasks


def add_status_history(rng: random.Random, task: Task, created_at: datetime, now: datetime) -> None:
    """Record each step from To Do up to the task's current status, in time order."""
    steps = STATUS_FLOW[: STATUS_FLOW.index(task.status) + 1]
    changed_at = created_at
    previous = None
    for step in steps:
        task.status_history.append(
            TaskStatusHistory(from_status=previous, to_status=step,
                              changed_by=task.assignee or task.created_by, changed_at=changed_at)
        )
        previous = step
        # the next change happens a few days later, but never in the future
        changed_at = min(changed_at + timedelta(days=rng.randint(1, 6)), now)
    task.updated_at = changed_at


def create_time_entries(db: Session, rng: random.Random, tasks: list[Task], today: date) -> list[TimeEntry]:
    """Hours only go on tasks someone has started, on weekdays, at most 9 h per person per day."""
    workdays = previous_weekdays(today, WEEKS_OF_HISTORY * 7)
    worked_tasks = [t for t in tasks if t.assignee and t.status != TaskStatus.TODO]
    hours_per_day: dict[tuple[str, date], float] = {}  # (email, day) -> hours so far

    entries: list[TimeEntry] = []
    while len(entries) < TIME_ENTRY_COUNT:
        task = rng.choice(worked_tasks)
        # between the day the task was created and the day it was finished (or today)
        last_day = task.updated_at.date() if task.status == TaskStatus.DONE else today
        possible_days = [d for d in workdays if task.created_at.date() <= d <= last_day]
        if not possible_days:
            continue
        day = rng.choice(possible_days)
        hours = rng.choice([0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 6])

        key = (task.assignee.email, day)
        if hours_per_day.get(key, 0) + hours > MAX_HOURS_PER_DAY:
            continue  # this person's day is full; pick again
        hours_per_day[key] = hours_per_day.get(key, 0) + hours

        entries.append(TimeEntry(user=task.assignee, task=task, work_date=day,
                                 hours=hours, note=rng.choice(TIME_NOTES)))
    db.add_all(entries)
    return entries


def create_requirements(db: Session, tasks: list[Task]) -> list[Requirement]:
    """A requirement with UAC and test cases on each UAC / Requirements task (first 8)."""
    out = []
    for task in [t for t in tasks if t.task_type in (TaskType.UAC, TaskType.REQUIREMENTS)][:8]:
        feature = task.title.split(": ")[-1].replace("Write UAC for ", "")
        requirement = Requirement(
            project=task.project, task=task, title=f"The system shall support {feature}",
            description=f"Users can complete {feature} end to end, with validation and clear error messages.",
            kind="Functional", status="In Review", source="Manual", created_by=task.created_by,
        )
        requirement.criteria = [
            AcceptanceCriterion(position=1, given_text="a signed-in user with the right permissions",
                                when_text=f"they start {feature}", then_text="the form shows every required field"),
            AcceptanceCriterion(position=2, given_text="a required field is empty",
                                when_text="they submit", then_text="an inline error names the missing field"),
            AcceptanceCriterion(position=3, given_text="valid data", when_text="they submit",
                                then_text="a confirmation is shown and an audit entry is written"),
        ]
        requirement.test_cases = [
            TestCase(title=f"Happy path: {feature}", preconditions="User is signed in",
                     steps="Open the page\nFill every required field\nSubmit",
                     expected_result="Confirmation message is shown", priority=TaskPriority.HIGH),
            TestCase(title=f"Missing required field: {feature}", preconditions="User is signed in",
                     steps="Open the page\nLeave a required field empty\nSubmit",
                     expected_result="Inline error is shown and nothing is saved", priority=TaskPriority.MEDIUM),
        ]
        db.add(requirement)
        out.append(requirement)
    return out


def seed(db: Session, today: date | None = None, random_seed: int = 42) -> dict[str, int]:
    """Create all the demo data in one transaction and return how many rows of each."""
    today = today or date.today()
    rng = random.Random(random_seed)  # own random generator, so results repeat

    users = create_roles_and_users(db)
    projects = create_projects(db, users, today)
    tasks = create_tasks(db, rng, projects, today)
    entries = create_time_entries(db, rng, tasks, today)
    requirements = create_requirements(db, tasks)
    db.commit()  # all or nothing: if anything above failed, nothing is saved

    return {"users": len(users), "projects": len(projects), "tasks": len(tasks), "time_entries": len(entries),
            "requirements": len(requirements)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Load BA WorkTrack demo data.")
    parser.add_argument("--reset", action="store_true", help="delete all existing rows first")
    args = parser.parse_args()

    with SessionLocal() as db:
        if args.reset:
            reset_database(db)
        elif db.scalar(select(func.count()).select_from(User)):
            raise SystemExit("The database already has users. Run with --reset to wipe it and seed again.")

        counts = seed(db)

    print("Seeded:", ", ".join(f"{n} {name}" for name, n in counts.items()))
    print(f"Log in as admin@demo.com (or any demo user) with password {DEMO_PASSWORD}")
    print("Demo data only: never run the seed against a production database.")


if __name__ == "__main__":
    main()
