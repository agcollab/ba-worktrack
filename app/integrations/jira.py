"""JIRA connector: Jira Cloud (REST v3, email + API token) or Data Center / Server
(REST v2, personal access token). Set config["deployment"] = "server" for the latter."""
from datetime import date, datetime

import httpx

from app.integrations.base import BaseConnector, ConnectionInfo, ConnectorError, RemoteItem

FIELDS = ["summary", "description", "status", "priority", "issuetype", "duedate", "assignee",
          "updated", "timeoriginalestimate"]
PRIORITY_MAP = {"highest": "Critical", "blocker": "Critical", "critical": "Critical", "high": "High",
                "major": "High", "medium": "Medium", "low": "Low", "lowest": "Low", "minor": "Low", "trivial": "Low"}
CATEGORY_MAP = {"new": "To Do", "indeterminate": "In Progress", "done": "Done"}


def adf_to_text(node) -> str:
    """Flatten Atlassian Document Format (Jira Cloud rich text) into plain text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(adf_to_text(n) for n in node)
    kind = node.get("type")
    if kind == "text":
        return node.get("text", "")
    if kind == "hardBreak":
        return "\n"
    inner = adf_to_text(node.get("content", []))
    if kind == "listItem":
        return "• " + inner.strip() + "\n"
    if kind in ("paragraph", "heading", "codeBlock", "blockquote"):
        return inner.rstrip() + "\n\n"
    return inner


def text_to_adf(heading: str, blocks: list[tuple[str, list[str]]]) -> dict:
    content: list[dict] = [{"type": "heading", "attrs": {"level": 3}, "content": [{"type": "text", "text": heading}]}]
    for title, lines in blocks:
        if title:
            content.append({"type": "paragraph", "content": [{"type": "text", "text": title, "marks": [{"type": "strong"}]}]})
        items = [{"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": line}]}]}
                 for line in lines if line.strip()]
        if items:
            content.append({"type": "bulletList", "content": items})
    content.append({"type": "paragraph", "content": [{"type": "text", "text": "Posted from BA WorkTrack",
                                                      "marks": [{"type": "em"}]}]})
    return {"type": "doc", "version": 1, "content": content}


def text_to_wiki(heading: str, blocks: list[tuple[str, list[str]]]) -> str:
    parts = [f"h3. {heading}"]
    for title, lines in blocks:
        if title:
            parts.append(f"*{title}*")
        parts.extend(f"* {line}" for line in lines if line.strip())
    parts.append("_Posted from BA WorkTrack_")
    return "\n".join(parts)


class JiraConnector(BaseConnector):
    kind = "jira"
    label = "JIRA"
    default_status_map = {"To Do": "To Do", "In Progress": "In Progress", "In Review": "In Review", "Done": "Done"}

    @property
    def is_cloud(self) -> bool:
        return self.config.get("deployment", "cloud") != "server"

    @property
    def api(self) -> str:
        return "/rest/api/3" if self.is_cloud else "/rest/api/2"

    def _auth(self) -> httpx.Auth | None:
        if self.is_cloud:
            if not self.username:
                raise ConnectorError("Jira Cloud needs the account email as the user name.")
            return httpx.BasicAuth(self.username, self.token)
        return None

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        if not self.is_cloud:
            kwargs.setdefault("headers", {})["Authorization"] = f"Bearer {self.token}"
        return super().request(method, url, **kwargs)

    # ---- interface ----------------------------------------------------------
    def test_connection(self) -> ConnectionInfo:
        me = self.request("GET", f"{self.api}/myself").json()
        project = self.request("GET", f"{self.api}/project/{self.project}").json()
        who = me.get("displayName") or me.get("emailAddress") or me.get("name") or "unknown user"
        return ConnectionInfo(True, f"Connected as {who}. Project {project.get('key')} – {project.get('name')}.")

    def _jql(self) -> str:
        return self.config.get("jql") or f'project = "{self.project}" ORDER BY updated DESC'

    def _search(self, jql: str, limit: int) -> list[RemoteItem]:
        items: list[RemoteItem] = []
        if self.is_cloud:
            token = None
            while len(items) < limit:
                body = {"jql": jql, "fields": FIELDS, "maxResults": min(100, limit - len(items))}
                if token:
                    body["nextPageToken"] = token
                data = self.request("POST", f"{self.api}/search/jql", json=body).json()
                items.extend(self._to_item(issue) for issue in data.get("issues", []))
                token = data.get("nextPageToken")
                if not token or data.get("isLast", True):
                    break
        else:
            start = 0
            while len(items) < limit:
                params = {"jql": jql, "fields": ",".join(FIELDS), "startAt": start,
                          "maxResults": min(100, limit - len(items))}
                data = self.request("GET", f"{self.api}/search", params=params).json()
                issues = data.get("issues", [])
                items.extend(self._to_item(issue) for issue in issues)
                start += len(issues)
                if not issues or start >= data.get("total", 0):
                    break
        return items[:limit]

    def fetch_items(self, limit: int = 200) -> list[RemoteItem]:
        return self._search(self._jql(), limit)

    def get_items(self, external_ids: list[str]) -> list[RemoteItem]:
        out: list[RemoteItem] = []
        for i in range(0, len(external_ids), 50):
            keys = ", ".join(f'"{k}"' for k in external_ids[i:i + 50])
            out.extend(self._search(f"key in ({keys})", 50))
        return out

    def create_item(self, title: str, description: str | None, item_type: str | None = None) -> RemoteItem:
        issue_type = item_type or self.config.get("issue_type") or "Task"
        fields: dict = {"project": {"key": self.project}, "summary": title[:250], "issuetype": {"name": issue_type}}
        if description:
            fields["description"] = (
                {"type": "doc", "version": 1, "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": para}]}
                    for para in description.split("\n\n") if para.strip()]}
                if self.is_cloud else description
            )
        created = self.request("POST", f"{self.api}/issue", json={"fields": fields}).json()
        return self.get_items([created["key"]])[0]

    def update_status(self, external_id: str, remote_status: str) -> None:
        data = self.request("GET", f"{self.api}/issue/{external_id}/transitions").json()
        wanted = remote_status.strip().lower()
        for transition in data.get("transitions", []):
            to_name = (transition.get("to") or {}).get("name", "")
            if to_name.lower() == wanted or transition.get("name", "").lower() == wanted:
                self.request("POST", f"{self.api}/issue/{external_id}/transitions",
                             json={"transition": {"id": transition["id"]}})
                return
        available = ", ".join(sorted({(t.get("to") or {}).get("name", t.get("name", "")) for t in data.get("transitions", [])}))
        raise ConnectorError(f"{external_id} cannot move to '{remote_status}' from its current status in JIRA. "
                             f"Available: {available or 'none'}. Adjust the status mapping.")

    def add_comment(self, external_id: str, heading: str, blocks: list[tuple[str, list[str]]]) -> None:
        body = text_to_adf(heading, blocks) if self.is_cloud else text_to_wiki(heading, blocks)
        self.request("POST", f"{self.api}/issue/{external_id}/comment", json={"body": body})

    # ---- mapping -------------------------------------------------------------
    def _to_item(self, issue: dict) -> RemoteItem:
        fields = issue.get("fields", {})
        status = fields.get("status") or {}
        category = ((status.get("statusCategory") or {}).get("key") or "").lower()
        priority = (fields.get("priority") or {}).get("name", "")
        assignee = fields.get("assignee") or {}
        description = fields.get("description")
        estimate = fields.get("timeoriginalestimate")
        return RemoteItem(
            external_id=issue["key"],
            title=fields.get("summary") or issue["key"],
            status=status.get("name", ""),
            status_hint=CATEGORY_MAP.get(category),
            url=f"{self.base_url}/browse/{issue['key']}",
            description=(adf_to_text(description) if isinstance(description, dict) else description or "").strip() or None,
            priority=PRIORITY_MAP.get(priority.lower()),
            item_type=(fields.get("issuetype") or {}).get("name"),
            due_date=date.fromisoformat(fields["duedate"]) if fields.get("duedate") else None,
            assignee_email=assignee.get("emailAddress"),
            estimate_hours=round(estimate / 3600, 2) if estimate else None,
            updated_at=_parse_dt(fields.get("updated")),
            raw=issue,
        )


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
