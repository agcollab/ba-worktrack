# Architecture

BA WorkTrack is a server-rendered FastAPI application. Pages are Jinja2 templates; HTMX swaps
fragments for interactive parts (filters, status changes, comments, timer, AI review) so there is
no front-end build step. A JSON API under `/api/v1` serves scripts and other tools.

```
app/
  main.py            app factory: middleware, routers, error handlers, start-up (first admin, scheduler)
  config.py          settings from environment / .env
  database.py        engine, session, Base
  security.py        bcrypt, JWT, CSRF tokens, Fernet encryption of stored secrets
  deps.py            current user, role checks, CSRF check (FastAPI dependencies)
  middleware.py      request id, security headers, CSRF cookie, flash messages, request log
  templating.py      Jinja2 environment, render() and toast() helpers, filters
  scheduler.py       APScheduler jobs: weekly report (Friday), integration sync
  models/            SQLAlchemy models (see docs/er-diagram.md)
  services/          business rules: users, projects, tasks + workflow, time tracking, requirements, audit
  reports/           metrics, table builders, CSV/Excel/PDF exporters, weekly report
  integrations/      JIRA and Azure DevOps connectors and sync (see docs/integrations.md)
  ai/                Ollama provider, prompts (versioned files), output schemas, AI Studio flow
  routers/           HTTP layer only: parse input, call a service, render a page or fragment
  schemas/           pydantic models for the JSON API
  templates/         Jinja2 pages and HTMX fragments (files starting with _ are fragments)
  static/            CSS, JS, vendored libraries (Bootstrap, HTMX, Chart.js, SortableJS)
alembic/             database migrations
scripts/seed.py      demo data
tests/               pytest suite (in-memory SQLite, mocked JIRA/ADO/Ollama)
```

## Rules the code follows

- **Routers stay thin.** Validation and permissions live in `services/`, which raise
  `ServiceError` / `NotFound` / `Forbidden`. `main.py` turns those into the right response for the
  caller: a JSON error for the API, a toast for HTMX, a flash message and redirect for a form.
- **Visibility.** `services.projects.visible_project_ids(user)` returns `None` for PMs and Admins
  (everything) or the ids of a BA's projects; every list, metric and export filters through it.
- **Every change worth tracing** (logins, user and role changes, deletes, integration runs)
  is written with `services.audit.record`.
- **No inline JavaScript.** The Content-Security-Policy forbids it. Data for charts goes into
  `<script type="application/json">` tags (`json_script`), and behaviour is attached in
  `static/js/app.js` through `data-*` attributes.
- **Background jobs** run in-process with APScheduler. With several web workers, set
  `SCHEDULER_ENABLED=true` on one of them only.

## AI Studio

`ai/studio.py` builds the prompt from a versioned template in `ai/prompts/`, calls the provider,
parses the reply as JSON and validates it with the pydantic schema for that feature. On invalid
output it retries (up to 3 attempts) and tells the model what was wrong. Every attempt is written to
`ai_generation_logs` with timings and the outcome (accepted, edited, rejected). Nothing is saved to
requirements until the user reviews it.
