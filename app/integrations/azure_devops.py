"""Azure DevOps Boards connector (REST API 7.1, personal access token)."""
import html
import re
from datetime import date, datetime
from urllib.parse import quote

import httpx

from app.config import settings
from app.integrations.base import BaseConnector, ConnectionInfo, ConnectorError, RemoteItem

API = "api-version=7.1"
FIELDS = [
    "System.Id", "System.Title", "System.Description", "System.State", "System.WorkItemType",
    "System.AssignedTo", "System.ChangedDate", "Microsoft.VSTS.Common.Priority",
    "Microsoft.VSTS.Scheduling.DueDate", "Microsoft.VSTS.Scheduling.TargetDate",
    "Microsoft.VSTS.Scheduling.OriginalEstimate",
]
PRIORITY_MAP = {1: "Critical", 2: "High", 3: "Medium", 4: "Low"}
LOCAL_TO_ADO_PRIORITY = {"Critical": 1, "High": 2, "Medium": 3, "Low": 4}


def html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"<\s*(br|/p|/div|/li)\s*/?>", "\n", value, flags=re.I)
    text = re.sub(r"<li[^>]*>", "• ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip() or None


class AzureDevOpsConnector(BaseConnector):
    kind = "ado"
    label = "Azure DevOps"
    # Agile process states. Scrum uses New / Approved / Committed / Done; edit the mapping to match.
    default_status_map = {"To Do": "New", "In Progress": "Active", "In Review": "Resolved", "Done": "Closed"}

    def _auth(self) -> httpx.Auth:
        return httpx.BasicAuth("", self.token)  # PAT goes in the password, user name empty

    @property
    def project_path(self) -> str:
        return "/" + quote(self.project, safe="")

    # ---- interface ----------------------------------------------------------
    def test_connection(self) -> ConnectionInfo:
        project = self.request("GET", f"/_apis/projects{self.project_path}?{API}").json()
        return ConnectionInfo(True, f"Connected. Project '{project.get('name')}' ({project.get('state', 'unknown')}).")

    def _wiql(self) -> str:
        extra = self.config.get("wiql_filter", "").strip()
        query = ("SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = @project "
                 "AND [System.State] <> 'Removed'")
        if self.config.get("area_path"):
            area = self.config["area_path"].replace("'", "''")
            query += f" AND [System.AreaPath] UNDER '{area}'"
        types = self.config.get("import_types") or []
        if types:
            names = ", ".join("'" + name.replace("'", "''") + "'" for name in types)
            query += f" AND [System.WorkItemType] IN ({names})"
        if extra:
            query += f" AND ({extra})"
        return query + " ORDER BY [System.ChangedDate] DESC"

    def fetch_items(self, limit: int = 200) -> list[RemoteItem]:
        data = self.request("POST", f"{self.project_path}/_apis/wit/wiql?$top={limit}&{API}",
                            json={"query": self._wiql()}).json()
        ids = [str(w["id"]) for w in data.get("workItems", [])][:limit]
        return self.get_items(ids)

    def fetch_item_types(self) -> list[tuple[str, str | None]]:
        types = self.request("GET", f"{self.project_path}/_apis/wit/workitemtypes?{API}").json().get("value", [])
        # Skip the types ADO hides from boards (Code Review Request, Shared Steps...)
        categories = self.request("GET", f"{self.project_path}/_apis/wit/workitemtypecategories?{API}").json()
        hidden = {t.get("name") for c in categories.get("value", []) if c.get("referenceName") == "Microsoft.HiddenCategory"
                  for t in c.get("workItemTypes", [])}
        return [(t["name"], t.get("description") or None) for t in types
                if t.get("name") and not t.get("isDisabled") and t["name"] not in hidden]

    def get_items(self, external_ids: list[str]) -> list[RemoteItem]:
        items: list[RemoteItem] = []
        for i in range(0, len(external_ids), 200):  # the batch API takes 200 ids at a time
            chunk = [int(x) for x in external_ids[i:i + 200]]
            if not chunk:
                continue
            data = self.request("POST", f"{self.project_path}/_apis/wit/workitemsbatch?{API}",
                                json={"ids": chunk, "fields": FIELDS, "errorPolicy": "omit"}).json()
            items.extend(self._to_item(w) for w in data.get("value", []) if w)
        return items

    def create_item(self, title: str, description: str | None, item_type: str | None = None) -> RemoteItem:
        work_item_type = item_type or self.config.get("work_item_type") or "Task"
        patch = [{"op": "add", "path": "/fields/System.Title", "value": title[:250]}]
        if description:
            patch.append({"op": "add", "path": "/fields/System.Description",
                          "value": "<br>".join(html.escape(line) for line in description.splitlines())})
        if self.config.get("area_path"):
            patch.append({"op": "add", "path": "/fields/System.AreaPath", "value": self.config["area_path"]})
        created = self.request(
            "POST", f"{self.project_path}/_apis/wit/workitems/${work_item_type}?{API}",
            json=patch, headers={"Content-Type": "application/json-patch+json"},
        ).json()
        return self._to_item(created)

    def update_status(self, external_id: str, remote_status: str) -> None:
        try:
            self.request(
                "PATCH", f"/_apis/wit/workitems/{int(external_id)}?{API}",
                json=[{"op": "add", "path": "/fields/System.State", "value": remote_status}],
                headers={"Content-Type": "application/json-patch+json"},
            )
        except ConnectorError as exc:
            raise ConnectorError(f"Work item {external_id} could not move to '{remote_status}': {exc}. "
                                 "Check the status mapping matches your process (Agile / Scrum / Basic).") from exc

    def add_comment(self, external_id: str, heading: str, blocks: list[tuple[str, list[str]]]) -> None:
        parts = [f"<h3>{html.escape(heading)}</h3>"]
        for title, lines in blocks:
            if title:
                parts.append(f"<p><b>{html.escape(title)}</b></p>")
            items = "".join(f"<li>{html.escape(line)}</li>" for line in lines if line.strip())
            if items:
                parts.append(f"<ul>{items}</ul>")
        parts.append(f"<p><i>Posted from {html.escape(settings.APP_NAME)}</i></p>")
        self.request("POST", f"{self.project_path}/_apis/wit/workItems/{int(external_id)}/comments?api-version=7.1-preview.4",
                     json={"text": "".join(parts)})

    # ---- mapping -------------------------------------------------------------
    def _to_item(self, work_item: dict) -> RemoteItem:
        fields = work_item.get("fields", {})
        assigned = fields.get("System.AssignedTo") or {}
        due = fields.get("Microsoft.VSTS.Scheduling.DueDate") or fields.get("Microsoft.VSTS.Scheduling.TargetDate")
        work_item_id = str(work_item.get("id") or fields.get("System.Id"))
        if not work_item_id or work_item_id == "None":
            raise ConnectorError("Azure DevOps returned a work item without an id.")
        return RemoteItem(
            external_id=work_item_id,
            title=fields.get("System.Title") or f"Work item {work_item_id}",
            status=fields.get("System.State", ""),
            url=f"{self.base_url}{self.project_path}/_workitems/edit/{work_item_id}",
            description=html_to_text(fields.get("System.Description")),
            priority=PRIORITY_MAP.get(fields.get("Microsoft.VSTS.Common.Priority")),
            item_type=fields.get("System.WorkItemType"),
            due_date=_parse_date(due),
            assignee_email=(assigned.get("uniqueName") if isinstance(assigned, dict) else None),
            estimate_hours=fields.get("Microsoft.VSTS.Scheduling.OriginalEstimate"),
            updated_at=_parse_dt(fields.get("System.ChangedDate")),
            raw=work_item,
        )


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None


def _parse_date(value: str | None) -> date | None:
    parsed = _parse_dt(value)
    return parsed.date() if parsed else None
