"""The plugin interface every connector (JIRA, Azure DevOps, ...) implements.

To add a new system (Trello, GitHub Issues, Redmine) write a class that inherits
BaseConnector, implement the abstract methods, and register it in registry.py.
See docs/integrations.md.
"""
import logging
import random
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime

import httpx

logger = logging.getLogger("app.integrations")

RETRY_STATUSES = {429, 500, 502, 503, 504}


class ConnectorError(Exception):
    """Anything that went wrong talking to the remote system, in words an admin can act on."""


@dataclass
class RemoteItem:
    external_id: str
    title: str
    status: str
    url: str | None = None
    description: str | None = None
    # Our own status the remote one most likely means, when the system tells us (JIRA status category)
    status_hint: str | None = None
    priority: str | None = None  # already in our vocabulary: Low / Medium / High / Critical
    item_type: str | None = None  # remote type name: Story, Bug, User Story...
    due_date: date | None = None
    assignee_email: str | None = None
    estimate_hours: float | None = None
    updated_at: datetime | None = None
    raw: dict = field(default_factory=dict, repr=False)


@dataclass
class ConnectionInfo:
    ok: bool
    message: str


class BaseConnector(ABC):
    kind: str = ""
    label: str = ""
    # Our TaskStatus value -> the remote status name used when nothing is configured
    default_status_map: dict[str, str] = {}

    def __init__(
        self,
        base_url: str,
        project: str,
        token: str,
        username: str | None = None,
        config: dict | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_retries: int = 3,
        timeout: float = 30.0,
    ):
        if not base_url:
            raise ConnectorError("Base URL is required.")
        if not project:
            raise ConnectorError("Remote project is required.")
        if not token:
            raise ConnectorError("API token / PAT is required.")
        self.base_url = base_url.rstrip("/")
        self.project = project
        self.token = token
        self.username = username
        self.config = config or {}
        self._sleep = sleep
        self._max_retries = max_retries
        self._client = httpx.Client(transport=transport, timeout=timeout, headers={"Accept": "application/json"},
                                    follow_redirects=False)

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---- HTTP with retries ------------------------------------------------
    def _auth(self) -> httpx.Auth | None:
        return None

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Send a request, retrying on rate limits (429) and server errors with backoff."""
        if not url.startswith("http"):
            url = self.base_url + url
        attempt = 0
        while True:
            try:
                response = self._client.request(method, url, auth=self._auth(), **kwargs)
            except httpx.TimeoutException as exc:
                if attempt >= self._max_retries:
                    raise ConnectorError(f"{self.label} did not answer in time.") from exc
                response = None
            except httpx.HTTPError as exc:
                raise ConnectorError(f"Could not reach {self.label}: {exc}") from exc
            if response is not None and response.status_code not in RETRY_STATUSES:
                break
            if attempt >= self._max_retries:
                break
            delay = self._retry_delay(response, attempt)
            logger.warning("%s %s -> %s, retrying in %.1fs", method, url,
                           response.status_code if response is not None else "timeout", delay)
            self._sleep(delay)
            attempt += 1
        if response is None:
            raise ConnectorError(f"{self.label} did not answer in time.")
        if response.status_code in (401, 403):
            raise ConnectorError(f"{self.label} refused the credentials ({response.status_code}). "
                                 "Check the user name and token, and that the token can access this project.")
        if response.status_code == 404:
            raise ConnectorError(f"{self.label} could not find {url.replace(self.base_url, '')} (404). "
                                 "Check the base URL and project.")
        if response.status_code == 429:
            raise ConnectorError(f"{self.label} rate limit reached; try again in a few minutes.")
        if response.status_code >= 400:
            raise ConnectorError(f"{self.label} error {response.status_code}: {self._error_text(response)}")
        return response

    @staticmethod
    def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
        if response is not None:
            retry_after = response.headers.get("retry-after")
            if retry_after and retry_after.isdigit():
                return min(60.0, float(retry_after))
        return min(30.0, (2 ** attempt) + random.random())

    @staticmethod
    def _error_text(response: httpx.Response) -> str:
        try:
            data = response.json()
        except ValueError:
            return response.text[:300]
        if isinstance(data, dict):
            messages = data.get("errorMessages") or []
            errors = data.get("errors") or {}
            if messages or errors:
                return "; ".join([*messages, *(f"{k}: {v}" for k, v in errors.items())])[:300]
            if "message" in data:
                return str(data["message"])[:300]
        return str(data)[:300]

    # ---- what every connector must do ------------------------------------
    @abstractmethod
    def test_connection(self) -> ConnectionInfo:
        """Check the credentials and that the project exists."""

    @abstractmethod
    def fetch_items(self, limit: int = 200) -> list[RemoteItem]:
        """Items to import, newest first."""

    @abstractmethod
    def get_items(self, external_ids: list[str]) -> list[RemoteItem]:
        """Current state of specific items (used by status sync)."""

    @abstractmethod
    def create_item(self, title: str, description: str | None, item_type: str | None = None) -> RemoteItem:
        """Create an issue / work item from a local task."""

    @abstractmethod
    def update_status(self, external_id: str, remote_status: str) -> None:
        """Move the remote item to remote_status."""

    @abstractmethod
    def add_comment(self, external_id: str, heading: str, blocks: list[tuple[str, list[str]]]) -> None:
        """Post a formatted comment. blocks = [(sub-heading, [lines])]."""

    # ---- helpers shared by connectors -------------------------------------
    @staticmethod
    def guess_local_status(remote_status: str) -> str | None:
        """Our status for common remote status names (used when no mapping matches)."""
        name = (remote_status or "").strip().lower()
        groups = {
            "To Do": {"to do", "todo", "new", "open", "backlog", "proposed", "selected for development",
                      "approved", "ready"},
            "In Progress": {"in progress", "active", "committed", "doing", "in development", "development"},
            "In Review": {"in review", "review", "resolved", "code review", "testing", "in test", "qa",
                          "ready for review", "uat"},
            "Done": {"done", "closed", "completed", "complete", "released"},
        }
        for local, names in groups.items():
            if name in names:
                return local
        return None
