#!/usr/bin/env python3
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_MARKER = "<!-- codemate:evaluation-gate-summary -->"
DEFAULT_API_URL = "https://api.github.com"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create or update a GitHub PR comment identified by a fixed marker."
    )
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY"),
        help="GitHub repository in owner/name form. Defaults to $GITHUB_REPOSITORY.",
    )
    parser.add_argument(
        "--pr-number",
        type=int,
        default=default_pr_number(),
        help="Pull request number. Defaults to the pull_request number in $GITHUB_EVENT_PATH.",
    )
    parser.add_argument("--body-file", required=True, help="Markdown file to publish as the comment body.")
    parser.add_argument(
        "--marker",
        default=DEFAULT_MARKER,
        help="Hidden marker used to find the existing CodeMate comment.",
    )
    parser.add_argument(
        "--api-url",
        default=os.environ.get("GITHUB_API_URL", DEFAULT_API_URL),
        help="GitHub API base URL. Defaults to $GITHUB_API_URL or https://api.github.com.",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"),
        help="GitHub token. Defaults to $GITHUB_TOKEN or $GH_TOKEN.",
    )
    args = parser.parse_args()

    if not args.repo:
        parser.error("--repo is required when $GITHUB_REPOSITORY is not set")
    if not args.pr_number:
        parser.error("--pr-number is required when $GITHUB_EVENT_PATH does not contain a pull_request")
    if not args.token:
        parser.error("--token is required when $GITHUB_TOKEN or $GH_TOKEN is not set")

    body = Path(args.body_file).read_text(encoding="utf-8")
    result = upsert_pr_comment(
        api_url=args.api_url,
        repo=args.repo,
        pr_number=args.pr_number,
        token=args.token,
        marker=args.marker,
        body=body,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def default_pr_number() -> int | None:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        return None
    path = Path(event_path)
    if not path.exists():
        return None
    try:
        event = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    pull_request = event.get("pull_request")
    if isinstance(pull_request, dict) and pull_request.get("number"):
        return int(pull_request["number"])
    if event.get("number"):
        return int(event["number"])
    return None


def upsert_pr_comment(
    *,
    api_url: str,
    repo: str,
    pr_number: int,
    token: str,
    marker: str,
    body: str,
) -> dict[str, Any]:
    comment_body = body_with_marker(body=body, marker=marker)
    existing_comment = find_existing_comment(
        comments=list_issue_comments(
            api_url=api_url,
            repo=repo,
            issue_number=pr_number,
            token=token,
        ),
        marker=marker,
    )
    if existing_comment is not None:
        comment = update_issue_comment(
            api_url=api_url,
            repo=repo,
            comment_id=int(existing_comment["id"]),
            token=token,
            body=comment_body,
        )
        action = "updated"
    else:
        comment = create_issue_comment(
            api_url=api_url,
            repo=repo,
            issue_number=pr_number,
            token=token,
            body=comment_body,
        )
        action = "created"

    return {
        "action": action,
        "comment_id": comment.get("id"),
        "html_url": comment.get("html_url"),
        "marker": marker,
    }


def body_with_marker(*, body: str, marker: str) -> str:
    normalized = body.rstrip()
    if marker in normalized:
        return normalized + "\n"
    return f"{marker}\n{normalized}\n"


def find_existing_comment(
    *,
    comments: list[dict[str, Any]],
    marker: str,
) -> dict[str, Any] | None:
    matches = [comment for comment in comments if marker in str(comment.get("body") or "")]
    return matches[-1] if matches else None


def list_issue_comments(
    *,
    api_url: str,
    repo: str,
    issue_number: int,
    token: str,
) -> list[dict[str, Any]]:
    comments: list[dict[str, Any]] = []
    page = 1
    while True:
        path = f"/repos/{quote_repo(repo)}/issues/{issue_number}/comments"
        query = urllib.parse.urlencode({"per_page": 100, "page": page})
        page_comments = github_json_request(
            method="GET",
            api_url=api_url,
            path=f"{path}?{query}",
            token=token,
        )
        if not isinstance(page_comments, list):
            raise RuntimeError("GitHub comments API returned an unexpected response")
        comments.extend(page_comments)
        if len(page_comments) < 100:
            return comments
        page += 1


def create_issue_comment(
    *,
    api_url: str,
    repo: str,
    issue_number: int,
    token: str,
    body: str,
) -> dict[str, Any]:
    response = github_json_request(
        method="POST",
        api_url=api_url,
        path=f"/repos/{quote_repo(repo)}/issues/{issue_number}/comments",
        token=token,
        payload={"body": body},
    )
    if not isinstance(response, dict):
        raise RuntimeError("GitHub create comment API returned an unexpected response")
    return response


def update_issue_comment(
    *,
    api_url: str,
    repo: str,
    comment_id: int,
    token: str,
    body: str,
) -> dict[str, Any]:
    response = github_json_request(
        method="PATCH",
        api_url=api_url,
        path=f"/repos/{quote_repo(repo)}/issues/comments/{comment_id}",
        token=token,
        payload={"body": body},
    )
    if not isinstance(response, dict):
        raise RuntimeError("GitHub update comment API returned an unexpected response")
    return response


def github_json_request(
    *,
    method: str,
    api_url: str,
    path: str,
    token: str,
    payload: dict[str, Any] | None = None,
) -> Any:
    data = None
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    url = f"{api_url.rstrip('/')}{path}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8")
        raise RuntimeError(f"GitHub API {method} {path} failed: {exc.code} {error_body}") from exc
    if not raw:
        return None
    return json.loads(raw)


def quote_repo(repo: str) -> str:
    parts = repo.split("/", maxsplit=1)
    if len(parts) != 2 or not all(parts):
        raise ValueError("Repository must be in owner/name form")
    return "/".join(urllib.parse.quote(part, safe="") for part in parts)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
