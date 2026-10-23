# Integrations: JIRA and Azure DevOps

Code lives in `app/integrations/`:

| File | Role |
|---|---|
| `base.py` | `BaseConnector` (the interface every connector implements), `RemoteItem`, HTTP `request()` with retries |
| `jira.py` | JIRA Cloud (REST v3, Atlassian Document Format) and Server/Data Center (REST v2, PAT) |
| `azure_devops.py` | Azure DevOps Services / Server (REST 7.1: WIQL, work item batch, JSON Patch) |
| `registry.py` | Maps an integration's `kind` to its connector class |
| `service.py` | Everything the app does with a connector: test, import, status sync, push, scheduled sync, sync log |

Connectors talk to the REST APIs directly with `httpx` (no vendor SDKs). Requests are retried with
exponential backoff on 429 and 5xx responses and honour `Retry-After`. Error messages from the remote
system are shortened and shown to the user; tokens never appear in logs or messages.

## Credentials

The API token / PAT is typed into the integration form, encrypted with Fernet (`ENCRYPTION_KEY`,
or a key derived from `SECRET_KEY` when that is empty) and stored in `integrations.encrypted_token`.
It is decrypted only when a connector is built. Nothing secret goes into code, `.env.example` or
the repository.

## Import

`import_items` asks the connector for up to `max_items` items (JIRA: the project, or the JQL filter;
ADO: a WIQL query on the project, plus the optional extra condition and area path). Each item becomes
a task in the integration's local project, or updates the task already linked to it
(`tasks.external_source` + `external_id`). Remote types and priorities are mapped to local ones
(`DEFAULT_TYPE_MAP` and the connector's priority map), and the remote status is mapped through the
status mapping or, failing that, `guess_local_status`.

## Two-way status sync

Each linked task remembers what both sides looked like at the last sync:

- `external_status`: the remote status at the last sync
- `synced_status`: the local status at the last sync

On each sync (`sync_statuses`, by hand or every `SYNC_INTERVAL_MINUTES` for integrations with
*auto sync* on) the current remote status is fetched and compared:

| Local changed? | Remote changed? | Result |
|:-:|:-:|---|
| no | no | nothing |
| no | yes | remote status copied here (through the status mapping) |
| yes | no | local status pushed to the remote item (needs a mapping for that status) |
| yes | yes | **conflict**, resolved by the integration's policy |

Conflict policies: *remote wins* (default), *local wins*, or *log only*. With *log only* nothing
changes and the conflict is reported again on the next sync until someone resolves it by hand.
Every run writes a row to `sync_logs` with counts and the conflict details, shown on the
integration's page as the sync history.

Local status changes forced by a sync skip the workflow rules (a remote item can jump from
*New* to *Closed*) but are still recorded in the task's status history.

## Push

- **Push task** creates a JIRA issue / ADO work item from a local task and links the two.
- **Push requirements** posts the task's requirements, acceptance criteria (Given/When/Then) and
  test cases as one formatted comment on the linked item (ADF for JIRA Cloud, wiki markup for
  Server, HTML for ADO).

## Adding a connector

1. Create `app/integrations/<name>.py` with a class that subclasses `BaseConnector`, sets
   `kind = "<name>"`, a `label`, a `default_status_map`, and implements the six abstract methods
   (`test_connection`, `fetch_items`, `get_items`, `create_item`, `update_status`, `add_comment`).
   Use `self.request(...)` for HTTP calls to get retries and error handling.
2. Register it in `CONNECTORS` in `registry.py`.
3. If it needs extra settings, add them to `config_from_form` in `service.py` and to
   `templates/integrations/form.html`.
4. Add tests with `set_test_transport(httpx.MockTransport(handler))`, as in
   `tests/test_integrations.py`; no network access is needed.
