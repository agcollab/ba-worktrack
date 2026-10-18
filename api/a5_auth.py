"""A5: call an authenticated API with a token read from .env (never from code).

Setup:
  1. github.com -> Settings -> Developer settings -> Personal access tokens
     -> Fine-grained tokens -> Generate. Repository access: "All repositories"
     (or just ba-worktrack), Permissions -> Metadata: Read-only. Expiry: 30 days.
  2. In the repo root create a file called .env with one line:
         GITHUB_TOKEN=github_pat_xxxxxxxx
  3. git status  -> .env must NOT appear (the Python .gitignore excludes it).

Run:  python crash-course/api/a5_auth.py
"""
import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()                                   # reads .env into environment variables

token = os.getenv("GITHUB_TOKEN")               # None if missing (os.environ[...] would crash)
if not token:
    sys.exit("GITHUB_TOKEN is not set. Create a .env file in the repo root (see the top of this file).")

headers = {
    "Authorization": f"Bearer {token}",         # how GitHub knows who you are
    "Accept": "application/vnd.github+json",
}


def list_my_repos() -> list[dict]:
    """All repos for the logged-in user, following pagination."""
    repos: list[dict] = []
    url: str | None = "https://api.github.com/user/repos"
    params: dict | None = {"per_page": 30, "sort": "updated"}

    with httpx.Client(headers=headers, timeout=10) as client:   # reuses one connection
        while url:
            resp = client.get(url, params=params)
            if resp.status_code == 401:
                sys.exit("401 Unauthorized: the token is wrong or expired. Make a new one.")
            resp.raise_for_status()
            repos.extend(resp.json())

            # GitHub returns at most per_page items and puts the next page's URL
            # in the "Link" header. httpx parses it into resp.links for us.
            url = resp.links.get("next", {}).get("url")
            params = None                       # the next URL already contains the params

    return repos


def main() -> None:
    me = httpx.get("https://api.github.com/user", headers=headers, timeout=10)
    me.raise_for_status()
    print(f"Logged in as: {me.json()['login']}")
    print(f"Requests left this hour: {me.headers.get('x-ratelimit-remaining')}  (5000 with a token, 60 without)\n")

    for repo in list_my_repos():
        vis = "private" if repo["private"] else "public"
        print(f"{repo['full_name']:<40} {vis}")


if __name__ == "__main__":
    main()
