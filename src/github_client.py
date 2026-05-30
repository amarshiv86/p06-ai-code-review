import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"

SEVERITY_EMOJI = {
    "critical": "🔴",
    "major":    "🟠",
    "minor":    "🟡",
    "info":     "🔵",
}

CATEGORY_LABEL = {
    "security":        "Security",
    "performance":     "Performance",
    "correctness":     "Correctness",
    "style":           "Style",
    "maintainability": "Maintainability",
}


class GitHubClient:
    def __init__(self):
        self.token = os.environ.get("GITHUB_TOKEN")
        if not self.token:
            raise RuntimeError("GITHUB_TOKEN environment variable is required")
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def get_pr_diff(self, repo_full_name: str, pr_number: int) -> str:
        """Fetch the unified diff for a pull request."""
        url = f"{GITHUB_API}/repos/{repo_full_name}/pulls/{pr_number}"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                url,
                headers={**self.headers, "Accept": "application/vnd.github.v3.diff"},
            )
            resp.raise_for_status()
            return resp.text

    async def post_review(
        self,
        repo_full_name: str,
        pr_number: int,
        head_sha: str,
        review_result: dict[str, Any],
    ) -> None:
        """
        Post a GitHub pull request review with:
        - Inline comments per file/line
        - A summary review body
        """
        comments = self._build_inline_comments(review_result["comments"])
        body = self._build_summary_body(review_result)
        event = self._review_event(review_result["overall_severity"])

        url = f"{GITHUB_API}/repos/{repo_full_name}/pulls/{pr_number}/reviews"
        payload = {
            "commit_id": head_sha,
            "body": body,
            "event": event,
            "comments": comments,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=self.headers, json=payload)
            if resp.status_code not in (200, 201):
                logger.error(f"GitHub review post failed: {resp.status_code} {resp.text}")
                resp.raise_for_status()

        logger.info(f"Posted review to PR #{pr_number} with event={event}")

    def _build_inline_comments(self, comments: list[dict]) -> list[dict]:
        """Convert reviewer comments to GitHub's inline comment format."""
        inline = []
        for c in comments:
            emoji = SEVERITY_EMOJI.get(c["severity"], "🔵")
            category = CATEGORY_LABEL.get(c["category"], c["category"].title())
            body = (
                f"{emoji} **{category}** `{c['severity'].upper()}`\n\n"
                f"{c['body']}"
            )
            inline.append({
                "path": c["path"],
                "line": c["line"],
                "side": "RIGHT",
                "body": body,
            })
        return inline

    def _build_summary_body(self, review_result: dict) -> str:
        """Build the top-level review summary comment."""
        severity = review_result["overall_severity"]
        emoji = SEVERITY_EMOJI.get(severity, "🔵")
        summary = review_result.get("summary", "")
        comment_count = len(review_result.get("comments", []))

        counts: dict[str, int] = {}
        for c in review_result.get("comments", []):
            counts[c["severity"]] = counts.get(c["severity"], 0) + 1

        breakdown = " · ".join(
            f"{SEVERITY_EMOJI[s]} {n} {s}"
            for s, n in sorted(counts.items(), key=lambda x: ["critical","major","minor","info"].index(x[0]))
            if n > 0
        )

        lines = [
            f"## {emoji} AI Code Review — `{severity.upper()}`",
            "",
            summary,
            "",
            f"**{comment_count} inline comment(s)** found.{(' ' + breakdown) if breakdown else ''}",
            "",
            "---",
            "_Reviewed by [AI Code Review Bot](https://github.com) · "
            "Powered by HuggingFace Inference API_",
        ]
        return "\n".join(lines)

    def _review_event(self, severity: str) -> str:
        """Map overall severity to GitHub review event type."""
        if severity in ("critical", "major"):
            return "REQUEST_CHANGES"
        return "COMMENT"
