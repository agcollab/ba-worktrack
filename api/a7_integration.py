"""A7: the three core integration patterns, in plain Python.

1. Field mapping   - translate statuses between JIRA, Azure DevOps and BA WorkTrack
2. Retries         - try again (with growing waits) on 429 rate limits and 5xx errors
3. Pagination      - keep fetching pages until there are no more

Run:  python crash-course/api/a7_integration.py
"""
import time
from collections.abc import Callable
from typing import Protocol

# ---------------------------------------------------------------------------
# 1. FIELD MAPPING
# ---------------------------------------------------------------------------
# Each external status -> our status. A BA decides these rules, not the code.
TO_WORKTRACK: dict[str, dict[str, str | None]] = {
    "jira": {
        "To Do": "To Do",
        "In Progress": "In Progress",
        "In Review": "In Progress",
        "Done": "Done",
    },
    "ado": {                       # Azure DevOps "Agile" process states
        "New": "To Do",
        "Active": "In Progress",
        "Resolved": "In Progress", # built, but not yet verified -> still in progress for a BA
        "Closed": "Done",
        "Removed": None,           # None = don't import this item at all
    },
}

# Our status -> each external status (used when we PUSH changes out)
FROM_WORKTRACK: dict[str, dict[str, str]] = {
    "jira": {"To Do": "To Do", "In Progress": "In Progress", "Done": "Done"},
    "ado":  {"To Do": "New",   "In Progress": "Active",      "Done": "Closed"},
}


def to_worktrack(system: str, external_status: str) -> str | None:
    """Map an external status to ours. Unknown values fail loudly, not silently."""
    try:
        return TO_WORKTRACK[system][external_status]
    except KeyError:
        raise ValueError(f"No mapping for {system} status {external_status!r}") from None


def from_worktrack(system: str, status: str) -> str:
    return FROM_WORKTRACK[system][status]


# ---------------------------------------------------------------------------
# 2. RETRIES WITH EXPONENTIAL BACKOFF
# ---------------------------------------------------------------------------
class ResponseLike(Protocol):      # anything with these two attributes (an httpx.Response fits)
    status_code: int
    headers: dict


RETRY_CODES = {429, 500, 502, 503, 504}   # "slow down" and "server hiccup" - worth retrying


def call_with_retries(
    send: Callable[[], ResponseLike],
    max_attempts: int = 4,
    base_delay: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
) -> ResponseLike:
    """Call send(); on 429/5xx wait 1s, 2s, 4s... and try again.

    400/401/403/404 are NOT retried: asking again won't fix a bad request
    or a wrong password.
    """
    for attempt in range(1, max_attempts + 1):
        resp = send()
        if resp.status_code not in RETRY_CODES or attempt == max_attempts:
            return resp
        # Respect the server if it says how long to wait (Retry-After: 30)
        wait = float(resp.headers.get("Retry-After", base_delay * 2 ** (attempt - 1)))
        print(f"  attempt {attempt} got {resp.status_code}; waiting {wait:.0f}s")
        sleep(wait)
    raise AssertionError("unreachable")


# ---------------------------------------------------------------------------
# 3. PAGINATION
# ---------------------------------------------------------------------------
def fetch_all(fetch_page: Callable[[int, int], list[dict]], page_size: int = 50) -> list[dict]:
    """JIRA style: ask for startAt=0, 50, 100... until a short page comes back."""
    items: list[dict] = []
    start = 0
    while True:
        page = fetch_page(start, page_size)
        items.extend(page)
        if len(page) < page_size:      # fewer than asked for = last page
            return items
        start += page_size


# ---------------------------------------------------------------------------
# Demo with fake data (no network needed)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("1. Field mapping")
    for system, status in [("jira", "In Review"), ("ado", "Active"), ("ado", "Resolved"), ("ado", "Removed")]:
        print(f"  {system:<4} {status:<12} -> {to_worktrack(system, status)}")
    print(f"  WorkTrack 'Done' -> ADO {from_worktrack('ado', 'Done')!r}")
    try:
        to_worktrack("jira", "Blocked")
    except ValueError as e:
        print(f"  {e}")

    print("\n2. Retries (fake server: 503, 429, then 200)")

    class FakeResp:
        def __init__(self, code: int, headers: dict | None = None):
            self.status_code = code
            self.headers = headers or {}

    answers = iter([FakeResp(503), FakeResp(429, {"Retry-After": "3"}), FakeResp(200)])
    final = call_with_retries(lambda: next(answers), sleep=lambda s: None)  # don't really wait
    print(f"  final status: {final.status_code}")

    print("\n3. Pagination (fake JIRA with 120 issues, 50 per page)")
    all_issues = [{"key": f"PROJ-{n}"} for n in range(1, 121)]
    calls = []

    def fake_page(start: int, size: int) -> list[dict]:
        calls.append(start)
        return all_issues[start:start + size]

    got = fetch_all(fake_page)
    print(f"  fetched {len(got)} issues in {len(calls)} calls (startAt = {calls})")
