"""A3 + A8: call the public GitHub API and handle errors gracefully.

Run from the repo root:  python crash-course/api/a3_github.py
Try a wrong repo name:   python crash-course/api/a3_github.py agcollab no-such-repo
"""
import sys

import httpx

GITHUB_API = "https://api.github.com"


def get_repo(owner: str, repo: str) -> dict | None:
    """Return the repo's details as a dict, or None if anything went wrong."""
    url = f"{GITHUB_API}/repos/{owner}/{repo}"
    try:
        resp = httpx.get(
            url,
            timeout=10,                                       # never wait forever
            headers={"Accept": "application/vnd.github+json"},
        )
        resp.raise_for_status()                               # 4xx/5xx -> exception

    except httpx.HTTPStatusError as e:                        # server answered, but with an error
        code = e.response.status_code
        if code == 404:
            print(f"Not found: {owner}/{repo}. Check the spelling, or the repo is private.")
        elif code == 403 and e.response.headers.get("x-ratelimit-remaining") == "0":
            print("Rate limit hit (60 requests/hour without a token). Try again later.")
        else:
            print(f"GitHub returned {code}: {e.response.text[:200]}")
        return None

    except httpx.TimeoutException:                            # server too slow
        print("GitHub took longer than 10 seconds. Try again.")
        return None

    except httpx.RequestError as e:                           # no answer at all (offline, DNS, proxy)
        print(f"Network problem calling {e.request.url}: {e}")
        return None

    return resp.json()                                        # JSON text -> Python dict


def main() -> None:
    owner = sys.argv[1] if len(sys.argv) > 1 else "agcollab"
    repo = sys.argv[2] if len(sys.argv) > 2 else "ba-worktrack"

    data = get_repo(owner, repo)
    if data is None:
        sys.exit(1)                                           # non-zero exit = "failed"

    print(f"Name:           {data['full_name']}")
    print(f"Default branch: {data['default_branch']}")
    print(f"Visibility:     {data['visibility']}")
    print(f"Open issues:    {data['open_issues_count']}")
    print(f"Last pushed:    {data['pushed_at']}")


if __name__ == "__main__":
    main()
