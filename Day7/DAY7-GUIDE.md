# Day 7: database models, migrations, seed data

By tonight `worktrack.db` has all 17 tables the app needs, built by an Alembic migration, and full of demo data: 7 users, 2 projects, 50 BA tasks and 200 time entries over the last 6 weeks.

Tested here: the migration (upgrade, downgrade, upgrade again), the seed script, and all 14 tests pass. `alembic check` confirms the migration matches the models exactly.

## 0. Before you start (10 minutes)

**GitHub Issues (today's GitHub skill).** On github.com → your repo → **Issues** → **New issue**. Create six issues: "Day 7: database models", "Day 8: login and authentication", "Day 9: roles and admin", "Day 10: projects and tasks", "Day 11: comments, attachments, time tracking", "Day 12: dashboard, tests, MVP release". Note the number of the Day 7 issue (probably **#2**, because your Day 6 PR was #1).

```powershell
cd D:\Projects\ba_worktrack
git checkout main
git pull
git checkout -b feature/day07-models
.venv\Scripts\activate
pip install sqlalchemy alembic "passlib[bcrypt]" "bcrypt==4.0.1"
pip freeze > requirements.txt
```

**Why `bcrypt==4.0.1`:** passlib hasn't been updated in years and crashes with bcrypt 4.1 or newer ("password cannot be longer than 72 bytes"). I hit this while testing. Pinning 4.0.1 avoids it.

## 1. Copy the files (10 minutes)

Unzip `day07-files.zip` into `D:\Projects\ba_worktrack` (the repository root), and let it overwrite files. You end up with:

| Path | What it is |
|---|---|
| `app/database.py` | **Replaces your Day 6 file** (see below) |
| `app/models/*.py` | 11 files: the tables, one file per area |
| `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`, `alembic/versions/` | Migration setup |
| `scripts/__init__.py`, `scripts/seed.py` | Demo data |
| `tests/conftest.py`, `tests/test_models.py`, `tests/test_seed.py` | Tests |
| `docs/er-diagram.md` | The ER diagram |

**Why `database.py` changed** (rule 2 of the master prompt):
- `Base` gets a *naming convention*, so every constraint has a name like `fk_time_entries_task_id_tasks`. Alembic needs those names to change a table on SQLite later.
- Foreign keys are switched on for every SQLite connection. SQLite ignores `REFERENCES` otherwise, as you saw on Day 4.
- `engine`, `SessionLocal`, `Base` and `get_db()` keep their Day 6 names, so `main.py` and `test_health.py` still work.

Your `app/config.py` doesn't change. The files only need `settings.DATABASE_URL` from it.

**If `app/main.py` has `Base.metadata.create_all(...)`, delete that line.** From today Alembic creates the tables. If the app creates them first, `alembic upgrade head` fails with "table already exists".

## 2. Create the first migration (20 minutes)

```powershell
del worktrack.db                                    # only if one exists from Day 6
alembic revision --autogenerate -m "initial tables"
```
Expected: a list of "Detected added table ..." lines, then `Generating ...\alembic\versions\2026_10_19_xxxx-<id>_initial_tables.py ... done`.

Open that new file and read it. `upgrade()` has one `op.create_table(...)` per table, and `downgrade()` drops them again. This is the file you commit, and it's how every other copy of the database gets built.

```powershell
alembic upgrade head        # build the tables: "Running upgrade  -> <id>, initial tables"
alembic check               # "No new upgrade operations detected." = models and database match
alembic current             # shows <id> (head)
```

## 3. Seed the demo data (10 minutes)

```powershell
python -m scripts.seed
```
Expected:
```
Seeded: 7 users, 2 projects, 50 tasks, 200 time_entries
Log in as admin@demo.com (or any demo user) with password Passw0rd!
```
Running it again stops with "already has users". `python -m scripts.seed --reset` wipes all the data and seeds it again. Use `python -m`, not `python scripts\seed.py`, otherwise `from app...` can't be found.

| Email | Role | Projects |
|---|---|---|
| admin@demo.com | Admin | none |
| priya.pm@demo.com | PM | PAY (Payments Modernisation) |
| mark.pm@demo.com | PM | CRM (Customer Portal Revamp) |
| asha.ba@demo.com | BA | PAY |
| ben.ba@demo.com | BA | PAY and CRM |
| chen.ba@demo.com, dana.ba@demo.com | BA | CRM |

## 4. Look at it in DB Browser (30 minutes)

Open `worktrack.db` in DB Browser → **Execute SQL**. This is your Day 4 weekly-hours query. The only change is `u.name` → `u.full_name`, because the real users table has a `full_name` column:

```sql
SELECT u.full_name,
       strftime('%Y-%W', te.work_date) AS week,
       SUM(te.hours)                   AS total_hours
FROM time_entries te
JOIN users u ON u.id = te.user_id
GROUP BY u.full_name, week
ORDER BY week, total_hours DESC;
```
Expected: about 26 rows, one per BA per week, and nobody above about 45 hours.

Try these too:
```sql
-- each task's status journey
SELECT t.title, h.from_status, h.to_status, h.changed_at
FROM task_status_history h JOIN tasks t ON t.id = h.task_id
WHERE t.id = 1 ORDER BY h.id;

-- users and their roles (the many-to-many from Day 4 S7)
SELECT u.email, r.name FROM users u
JOIN user_roles ur ON ur.user_id = u.id JOIN roles r ON r.id = ur.role_id;
```
Also open the **Database Structure** tab, expand `time_entries`, and find the CHECK constraint and the foreign keys.

## 5. Run the tests (10 minutes)

```powershell
python -m pytest -v
```
Expected: **14 passed** from the new files, plus your Day 6 health test. The tests use an in-memory database, so they never touch `worktrack.db`. They take about 10 seconds because bcrypt is deliberately slow.

If you get `ModuleNotFoundError: No module named 'app'`, you ran plain `pytest`. Use `python -m pytest`, which adds the current folder to Python's search path.

## 6. The ER diagram (15 minutes)

Open `docs/er-diagram.md`. On github.com (after you push) it renders as a diagram. In VS Code, install **Markdown Preview Mermaid Support**, then press Ctrl+Shift+V. Follow one line in it, for example a TASK with its TIME_ENTRIES, back to the model in `app/models/task.py`.

## 7. Commit, PR, close the issue

Add three lines to `learning-log.md` (the explain-back rule), then:
```powershell
git status          # worktrack.db and .env must NOT be listed
git add .
git commit -m "Day 7: database models, migrations, seed data"
git push -u origin feature/day07-models
```
On GitHub: **Compare & pull request**. In the description, under your three headings (What changed / How I tested it / What I learned), add the line **`Closes #2`**, using your Day 7 issue number. Read **Files changed**, then merge. Open the Issues tab: issue #2 has closed itself. Then:
```powershell
git checkout main
git pull
git branch -d feature/day07-models
```

## What the code does (for your learning log)

- **Models are Python classes that describe tables.** `Mapped[str]` means a NOT NULL column, `Mapped[str | None]` means it may be empty, and `mapped_column(...)` adds details such as `unique=True`, `index=True` and `ForeignKey(...)`.
- **Relationships** (`relationship(back_populates=...)`) let you write `task.time_entries` or `entry.task` instead of writing a JOIN. `back_populates` keeps both sides in sync.
- **Many-to-many:** users and roles are joined through the `user_roles` link table (`secondary=user_roles`), the same design as Day 4 S7.
- **Enums** (`TaskStatus`, `TaskType`, `TaskPriority`) fix the allowed values. They're stored as readable text ("In Progress"), and anything else ("Finished") is refused before it reaches the database.
- **Constraints** protect the data even when the code has bugs: UNIQUE email, `CHECK (hours > 0 AND hours <= 24)`, and foreign keys with `ON DELETE CASCADE` (deleting a task deletes its hours) or `SET NULL` (deleting a user leaves the task unassigned).
- **Mixins:** `TimestampMixin` adds `created_at` and `updated_at` to any model that inherits it, so they're written once.
- **Alembic migrations** are version control for the database structure. `--autogenerate` compares the models with the database and writes the difference. `render_as_batch=True` lets later migrations alter SQLite tables.
- **Seed script:** one transaction (`db.commit()` at the end, so it's all or nothing), passwords hashed with bcrypt (a different salt each time), and `random.Random(42)` so the "random" data is the same on every run.
- **Fixtures** in `conftest.py` give every test a fresh, empty database, so the tests can't affect each other.

## Checkpoint
- ☐ `alembic upgrade head` and `alembic check` both run cleanly
- ☐ `python -m scripts.seed` prints 7 users, 2 projects, 50 tasks, 200 time_entries
- ☐ The weekly-hours query runs in DB Browser
- ☐ `python -m pytest -v` all green
- ☐ The PR is merged and the Day 7 issue closed itself
