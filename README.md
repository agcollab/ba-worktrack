# BA WorkTrack

A work-tracking tool for Business Analyst teams: tasks and a Kanban board, time tracking with
weekly timesheets, requirements with acceptance criteria and test cases, dashboards and weekly
reports, an AI Studio that drafts requirements on a local model, and two-way sync with
**JIRA** and **Azure DevOps**. Everything can be exported to **CSV, Excel and PDF**.

Built with FastAPI, SQLAlchemy 2 + Alembic, Jinja2 + HTMX, Bootstrap 5 and Chart.js.
It runs on SQLite on a laptop and PostgreSQL in production.

## Features

| Area | What you get |
|---|---|
| Accounts | Email + password login (bcrypt), JWT in an HttpOnly cookie, roles **Admin / PM / BA**, lockout after repeated failures, login rate limiting, password change after an admin reset, audit log |
| Projects | Projects with a key (e.g. `PAY`), owner, dates and members. BAs see only their projects; PMs and Admins see all |
| Tasks | List with search, filters, sorting and paging; status workflow *To Do → In Progress → In Review → Done* with history; comments; file attachments; overdue flags |
| Board | Kanban board with drag-and-drop (and keyboard moves) that respects the workflow |
| Time | Start/stop timer, manual entries with a 24 h/day limit, weekly timesheet with day and task totals |
| Requirements | Requirements linked to tasks, Given/When/Then acceptance criteria, test cases with pass/fail status |
| AI Studio | Drafts requirements, acceptance criteria and test cases with Ollama; output is validated against a JSON schema, retried on bad output and logged; you review and edit before saving |
| Dashboards & reports | KPIs, charts (status, hours by week/type/person, utilisation), filters by project, person and period; weekly report generated every Friday and kept for download |
| Integrations | JIRA Cloud / Server and Azure DevOps: import work items, two-way status sync with a status mapping and conflict policy, push tasks and requirements back, sync history |
| Export | Tasks, time entries, requirements, test cases and the full report as **CSV, Excel (.xlsx) and PDF**, honouring the current filters |
| API | JSON API under `/api/v1` with Bearer tokens, interactive docs at `/docs` |
| UI | Modern responsive layout, light and dark themes, toasts, quick search |

## Quick start (laptop, SQLite)

Requires Python 3.12 or newer.

```powershell
# Windows PowerShell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env          # then edit SECRET_KEY (see Configuration)
alembic upgrade head            # create the database
python -m scripts.seed          # optional: demo data
uvicorn app.main:app --reload
```

```bash
# macOS / Linux
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
python -m scripts.seed
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000. With the demo data, log in as `admin@demo.com` (Admin),
`priya.pm@demo.com` (PM) or `asha.ba@demo.com` (BA) with the password `Passw0rd!`. Without demo data, set `FIRST_ADMIN_EMAIL` and
`FIRST_ADMIN_PASSWORD` in `.env`; that admin is created on first start when there are no users.

> The database must be created by `alembic upgrade head`. If you have a `worktrack.db` from the
> learning exercises, delete it (or point `DATABASE_URL` at a new file) before migrating.

## Production with Docker (PostgreSQL)

```bash
cp .env.example .env
# set ENVIRONMENT=production, SECRET_KEY, ENCRYPTION_KEY, POSTGRES_PASSWORD,
# FIRST_ADMIN_EMAIL and FIRST_ADMIN_PASSWORD
docker compose up -d --build
docker compose --profile ai up -d          # optional: Ollama for AI Studio
docker compose exec ollama ollama pull llama3.1:8b
```

The container runs database migrations on start, then serves on port 8000 as a non-root user.
Uploads live in the `appdata` volume and the database in `pgdata`. Put a reverse proxy with
HTTPS in front (Caddy, nginx, Azure App Gateway…): in production the login cookie is marked
`Secure` and HSTS is sent, so the app must be reached over HTTPS.

Health check: `GET /health` returns `{"status": "ok"}` when the database answers.

## Configuration

All settings come from environment variables or `.env`; see [.env.example](.env.example) for the
full list with comments. The important ones:

| Variable | Purpose |
|---|---|
| `ENVIRONMENT` | `development` or `production`. Production refuses to start with the default secret |
| `SECRET_KEY` | Signs login tokens. `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `ENCRYPTION_KEY` | Fernet key that encrypts JIRA/ADO tokens in the database. `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Changing it means re-entering integration tokens |
| `DATABASE_URL` | `sqlite:///./worktrack.db` or `postgresql+psycopg://user:pass@host:5432/worktrack` |
| `AI_PROVIDER` | `ollama` or `disabled` (hides AI Studio) |
| `SCHEDULER_ENABLED` | Weekly report and integration sync jobs. With several workers, enable on one only |

## Roles

| | BA | PM | Admin |
|---|:-:|:-:|:-:|
| Own tasks, time, comments, attachments | ✓ | ✓ | ✓ |
| See tasks and reports of projects they belong to | ✓ | ✓ | ✓ |
| See all projects and the whole team's reports | | ✓ | ✓ |
| Manage projects, members and integrations | | ✓ | ✓ |
| Manage users, item types (read-only / editable), audit log and system page | | | ✓ |

## Connecting JIRA and Azure DevOps

Go to **Integrations → New integration** (PM or Admin). Tokens are encrypted before they are
stored and are never shown again; leave the token field blank when editing to keep the current one.

**JIRA Cloud**: base URL `https://your-site.atlassian.net`, your Atlassian email as username, and
an API token from https://id.atlassian.com/manage-profile/security/api-tokens. The account needs
*Browse projects*, *Create issues*, *Transition issues* and *Add comments* on the project.

**JIRA Server / Data Center**: choose *Server*, use the base URL of your JIRA, and a Personal
Access Token (username not needed).

**Azure DevOps**: base URL `https://dev.azure.com/your-org`, the project name, and a Personal
Access Token with the **Work Items (Read & write)** scope.

Then:

1. **Test connection** checks the credentials and the project.
2. **Item types** (on the integration page): **Fetch from JIRA/ADO** lists the project's types
   exactly as named there (Story, Bug, User Story, Feature...). Tick the ones to import, or none for
   all, and switch any type to **read-only**.
3. **Import** pulls work items (optionally filtered with JQL or a WIQL condition) into the linked
   local project, as tasks that link back to the source. Imported tasks keep their JIRA key
   (`PAY-123`) or ADO id (`4567`) as their key, and their remote item type.
4. **Status mapping** maps each local status to a remote status or transition name.
5. **Sync** (by hand, or every `SYNC_INTERVAL_MINUTES` when *auto sync* is on) compares both sides
   since the last sync. A change on one side is copied to the other; a change on both sides is a
   conflict, resolved by the integration's policy (*remote wins*, *local wins* or *log only*) and
   written to the sync history.
6. From a task you can **push** it to JIRA/ADO as a new item, and push its requirements, acceptance
   criteria and test cases as a comment on the linked item.

**Read-only item types.** Admins set each type to *editable* or *read-only* under **Admin → Item types**
(or on the integration page). Tasks of a read-only type can still be tracked here (time, timer, comments,
files, requirements), but their fields, status and deletion are locked in the app, the board and the API.
Changes made in JIRA/ADO still flow in on import and sync. New types start as editable.

See [docs/integrations.md](docs/integrations.md) for how the sync works and how to add a connector.

## Exports and reports

The task, timesheet, requirement and test-case pages have an **Export** menu (CSV, Excel, PDF)
that uses the filters on screen. The Reports
page exports the full report (summary, charts data, tasks, time) as a multi-sheet Excel workbook
or a branded PDF. Every Friday at 17:00 (configurable) a weekly report for the previous week is
generated and listed on the Reports page for download. CSV files open cleanly in Excel (UTF-8 BOM)
and cell values that look like formulas are escaped.

## Development

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest                     # unit and HTTP tests on an in-memory database
ruff check .               # lint
alembic revision --autogenerate -m "describe change"   # after changing a model
```

CI (GitHub Actions) runs lint and tests, applies the migrations to PostgreSQL, and builds the Docker
image. Project layout and design notes: [docs/architecture.md](docs/architecture.md); database:
[docs/er-diagram.md](docs/er-diagram.md).

## Security notes

- **Never commit secrets.** `.env` is ignored by Git; only `.env.example` (no real values) is committed.
  JIRA/ADO tokens are entered in the app and stored encrypted, never in code or config files.
- **A GitHub token was committed to this repository's history earlier.** Removing the file does not
  remove it from history: revoke that token at https://github.com/settings/tokens if you have not
  already, and create a new one if you still need it.
- Forms are protected by a CSRF token; responses carry a strict Content-Security-Policy (no inline
  scripts), `X-Frame-Options: DENY`, `nosniff` and, in production, HSTS.
- Uploads are limited by size and file type and stored under random names outside the web root.
- Logins are rate limited per IP and accounts lock after `MAX_FAILED_LOGINS` failures.

## Learning material

The `Day3`, `Day4`, `api` and `bruno` folders and the `.docx` plans are from the learning
exercises and are not used by the app.

## Licences

Front-end libraries are vendored under `app/static/vendor` (Bootstrap and Bootstrap Icons: MIT,
HTMX: 0BSD, Chart.js: MIT, SortableJS: MIT, Inter font: SIL OFL 1.1). PDF exports embed the
DejaVu fonts (free licence in `app/reports/fonts/LICENSE`).
