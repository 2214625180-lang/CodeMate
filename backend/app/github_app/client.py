import base64
import json
import time
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from app.core.config import settings


class GitHubAppError(RuntimeError):
    pass


class GitHubAppClient:
    """GitHub App installation client for CI reads and Draft PR writes."""

    FAILED_CONCLUSIONS = {"action_required", "failure", "startup_failure", "timed_out"}

    def __init__(self, *, api_url: str | None = None):
        self.api_url = (api_url or settings.github_app_api_url).rstrip("/")

    def read_failed_workflow_run(
        self,
        *,
        installation_id: str,
        owner: str,
        repository: str,
        workflow_run_id: str,
    ) -> dict:
        token = self.installation_token(installation_id)
        workflow = self._request(
            "GET",
            f"/repos/{owner}/{repository}/actions/runs/{workflow_run_id}",
            token=token,
        )
        conclusion = str(workflow.get("conclusion") or "").lower()
        if conclusion not in self.FAILED_CONCLUSIONS:
            raise GitHubAppError("GitHub workflow run is not in a repairable failed state")
        jobs = self._request(
            "GET",
            f"/repos/{owner}/{repository}/actions/runs/{workflow_run_id}/jobs",
            token=token,
        )
        repo_data = self._request("GET", f"/repos/{owner}/{repository}", token=token)
        full_name = str(repo_data.get("full_name") or "")
        if full_name.lower() != f"{owner}/{repository}".lower():
            raise GitHubAppError("GitHub repository identity does not match the requested repository")
        return {
            "repository_full_name": full_name,
            "workflow_run_id": str(workflow.get("id") or workflow_run_id),
            "workflow_url": workflow.get("html_url"),
            "head_sha": str(workflow.get("head_sha") or ""),
            "base_branch": str(repo_data.get("default_branch") or ""),
            "failure_summary": {
                "workflow_name": str(workflow.get("name") or "GitHub Actions")[:200],
                "conclusion": conclusion,
                "failed_jobs": self._failed_jobs(jobs.get("jobs") or []),
            },
        }

    def installation_token(self, installation_id: str) -> str:
        payload = self._request(
            "POST",
            f"/app/installations/{installation_id}/access_tokens",
            token=self._app_jwt(),
        )
        token = payload.get("token")
        if not isinstance(token, str) or not token:
            raise GitHubAppError("GitHub App installation token was not returned")
        return token

    def create_draft_pull_request(
        self,
        *,
        installation_id: str,
        owner: str,
        repository: str,
        branch_name: str,
        base_branch: str,
        title: str,
        body: str,
    ) -> dict:
        return self._request(
            "POST",
            f"/repos/{owner}/{repository}/pulls",
            token=self.installation_token(installation_id),
            json_body={
                "title": title[:256],
                "head": branch_name,
                "base": base_branch,
                "body": body[:65_000],
                "draft": True,
            },
        )

    def _app_jwt(self) -> str:
        if not settings.github_app_enabled:
            raise GitHubAppError("GitHub App integration is disabled")
        app_id = (settings.github_app_id or "").strip()
        private_key = (settings.github_app_private_key or "").replace("\\n", "\n").strip()
        if not app_id or not private_key:
            raise GitHubAppError("GitHub App ID and private key must be configured")
        now = int(time.time())
        header = self._base64url({"alg": "RS256", "typ": "JWT"})
        claims = self._base64url({"iat": now - 60, "exp": now + 540, "iss": app_id})
        signed = f"{header}.{claims}".encode("ascii")
        try:
            key = serialization.load_pem_private_key(private_key.encode("utf-8"), password=None)
            signature = key.sign(signed, padding.PKCS1v15(), hashes.SHA256())
        except Exception as exc:  # noqa: BLE001 - never disclose private-key details.
            raise GitHubAppError("GitHub App private key is invalid") from exc
        return f"{header}.{claims}.{self._base64url(signature)}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        token: str,
        json_body: dict | None = None,
    ) -> dict:
        try:
            with httpx.Client(timeout=20.0) as client:
                response = client.request(
                    method,
                    f"{self.api_url}{path}",
                    headers={
                        "Accept": "application/vnd.github+json",
                        "Authorization": f"Bearer {token}",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                    json=json_body,
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise GitHubAppError(f"GitHub API request failed: {exc}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise GitHubAppError("GitHub API returned an invalid JSON response") from exc
        if not isinstance(payload, dict):
            raise GitHubAppError("GitHub API returned an unexpected response")
        return payload

    @staticmethod
    def _failed_jobs(jobs: list[Any]) -> list[dict]:
        failed: list[dict] = []
        for job in jobs:
            if not isinstance(job, dict):
                continue
            conclusion = str(job.get("conclusion") or "").lower()
            if conclusion not in GitHubAppClient.FAILED_CONCLUSIONS:
                continue
            failed_steps = [
                str(step.get("name") or "")[:200]
                for step in job.get("steps") or []
                if isinstance(step, dict)
                and str(step.get("conclusion") or "").lower()
                in GitHubAppClient.FAILED_CONCLUSIONS
            ]
            failed.append(
                {
                    "name": str(job.get("name") or "job")[:200],
                    "conclusion": conclusion,
                    "failed_steps": failed_steps[:20],
                }
            )
        return failed[:20]

    @staticmethod
    def _base64url(value: dict | bytes) -> str:
        serialized = (
            json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
            if isinstance(value, dict)
            else value
        )
        return base64.urlsafe_b64encode(serialized).rstrip(b"=").decode("ascii")
