import json
import logging
import os
import re
from typing import Any

from huggingface_hub import AsyncInferenceClient

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a senior software engineer performing a thorough code review.
Analyze the provided git diff and return ONLY a JSON object — no markdown, no explanation outside the JSON.

JSON schema:
{
  "overall_severity": "critical" | "major" | "minor" | "info",
  "summary": "2-3 sentence overall assessment",
  "comments": [
    {
      "path": "relative/file/path.py",
      "line": <line number in the diff, integer>,
      "severity": "critical" | "major" | "minor" | "info",
      "category": "security" | "performance" | "correctness" | "style" | "maintainability",
      "body": "Specific, actionable feedback. Reference the code. Suggest a fix."
    }
  ]
}

Severity guide:
- critical: security vulnerability, data loss risk, crashes
- major: logic bug, significant performance issue, broken functionality
- minor: code smell, unclear naming, missing error handling
- info: style suggestion, minor improvement

Focus on real issues. Skip trivial whitespace or formatting comments.
Return valid JSON only."""


class CodeReviewer:
    def __init__(self):
        self.hf_token = os.environ.get("HF_TOKEN")
        self.model = os.environ.get("HF_MODEL", "mistralai/Mistral-7B-Instruct-v0.3")
        self.max_diff_chars = int(os.environ.get("MAX_DIFF_CHARS", "12000"))
        self.client = AsyncInferenceClient(token=self.hf_token)

    def _truncate_diff(self, diff: str) -> str:
        """Truncate large diffs to stay within model context limits."""
        if len(diff) <= self.max_diff_chars:
            return diff
        logger.warning(f"Diff truncated from {len(diff)} to {self.max_diff_chars} chars")
        return diff[: self.max_diff_chars] + "\n\n[... diff truncated for context limit ...]"

    def _parse_response(self, raw: str) -> dict[str, Any]:
        """Extract and parse JSON from model response, handling markdown fences."""
        # Strip markdown code fences if present
        cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip()
        # Find the first { ... } block
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise ValueError(f"No JSON object found in model response: {raw[:200]}")
        return json.loads(match.group())

    def _validate_result(self, result: dict) -> dict:
        """Ensure required fields exist with safe defaults."""
        valid_severities = {"critical", "major", "minor", "info"}
        if result.get("overall_severity") not in valid_severities:
            result["overall_severity"] = "info"
        if "summary" not in result:
            result["summary"] = "Review complete."
        if "comments" not in result or not isinstance(result["comments"], list):
            result["comments"] = []
        # Validate each comment
        clean_comments = []
        for c in result["comments"]:
            if not isinstance(c, dict):
                continue
            if not c.get("path") or not c.get("body"):
                continue
            c.setdefault("line", 1)
            c.setdefault("severity", "info")
            c.setdefault("category", "maintainability")
            clean_comments.append(c)
        result["comments"] = clean_comments
        return result

    async def review(self, diff: str, pr_title: str = "") -> dict[str, Any]:
        """
        Send diff to HF Inference API and return structured review result.
        """
        truncated_diff = self._truncate_diff(diff)

        user_message = f"PR Title: {pr_title}\n\nGit diff:\n```\n{truncated_diff}\n```"

        prompt = f"<s>[INST] {SYSTEM_PROMPT}\n\n{user_message} [/INST]"

        logger.info(f"Sending diff ({len(truncated_diff)} chars) to {self.model}")

        raw_response = await self.client.text_generation(
            prompt,
            model=self.model,
            max_new_tokens=2048,
            temperature=0.1,  # low temp for consistent structured output
            repetition_penalty=1.1,
        )

        result = self._parse_response(raw_response)
        result = self._validate_result(result)

        logger.info(
            f"Review parsed: {len(result['comments'])} comments, "
            f"severity={result['overall_severity']}"
        )
        return result
