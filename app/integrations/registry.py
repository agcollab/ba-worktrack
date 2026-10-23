"""Which connector class handles which kind of integration."""
import time

import httpx

from app.integrations.azure_devops import AzureDevOpsConnector
from app.integrations.base import BaseConnector
from app.integrations.jira import JiraConnector
from app.models import Integration
from app.security import decrypt_secret

CONNECTORS: dict[str, type[BaseConnector]] = {
    JiraConnector.kind: JiraConnector,
    AzureDevOpsConnector.kind: AzureDevOpsConnector,
}

# Lets tests swap in httpx.MockTransport so no real network calls happen
_test_transport: httpx.BaseTransport | None = None


def set_test_transport(transport: httpx.BaseTransport | None) -> None:
    global _test_transport
    _test_transport = transport


def build_connector(integration: Integration) -> BaseConnector:
    cls = CONNECTORS.get(integration.kind)
    if cls is None:
        raise ValueError(f"Unknown integration type: {integration.kind}")
    return cls(
        base_url=integration.base_url,
        project=integration.remote_project or "",
        token=decrypt_secret(integration.encrypted_token),
        username=integration.username,
        config=integration.config,
        transport=_test_transport,
        sleep=(lambda _seconds: None) if _test_transport else time.sleep,
    )
