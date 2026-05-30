import json
import pytest
from unittest.mock import AsyncMock, patch

from src.reviewer import CodeReviewer


SAMPLE_DIFF = """diff --git a/app.py b/app.py
index 1234567..abcdefg 100644
--- a/app.py
+++ b/app.py
@@ -1,10 +1,15 @@
+import os
 import sqlite3
 
+SECRET_KEY = "hardcoded_secret_123"
+
 def get_user(user_id):
-    conn = sqlite3.connect("db.sqlite")
-    cursor = conn.cursor()
-    cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")
+    conn = sqlite3.connect(os.getenv("DB_PATH", "db.sqlite"))
+    cursor = conn.cursor()
+    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
     return cursor.fetchone()
"""

SAMPLE_LLM_RESPONSE = json.dumps({
    "overall_severity": "critical",
    "summary": "Hardcoded secret key found. SQL injection partially fixed but secret leakage remains.",
    "comments": [
        {
            "path": "app.py",
            "line": 4,
            "severity": "critical",
            "category": "security",
            "body": "SECRET_KEY is hardcoded. Use os.getenv('SECRET_KEY') and store in environment variables.",
        },
        {
            "path": "app.py",
            "line": 9,
            "severity": "info",
            "category": "correctness",
            "body": "Good fix using parameterized query to prevent SQL injection.",
        },
    ],
})


class TestCodeReviewer:
    def setup_method(self):
        with patch.dict("os.environ", {"HF_TOKEN": "hf_test123"}):
            self.reviewer = CodeReviewer()

    def test_truncate_diff_short(self):
        short_diff = "a" * 100
        result = self.reviewer._truncate_diff(short_diff)
        assert result == short_diff

    def test_truncate_diff_long(self):
        long_diff = "a" * 20000
        result = self.reviewer._truncate_diff(long_diff)
        assert len(result) < 20000
        assert "truncated" in result

    def test_parse_response_clean_json(self):
        result = self.reviewer._parse_response(SAMPLE_LLM_RESPONSE)
        assert result["overall_severity"] == "critical"
        assert len(result["comments"]) == 2

    def test_parse_response_with_markdown_fence(self):
        wrapped = f"```json\n{SAMPLE_LLM_RESPONSE}\n```"
        result = self.reviewer._parse_response(wrapped)
        assert result["overall_severity"] == "critical"

    def test_parse_response_invalid_raises(self):
        with pytest.raises(ValueError):
            self.reviewer._parse_response("no json here at all")

    def test_validate_result_defaults(self):
        result = self.reviewer._validate_result({})
        assert result["overall_severity"] == "info"
        assert result["summary"] == "Review complete."
        assert result["comments"] == []

    def test_validate_result_filters_bad_comments(self):
        result = self.reviewer._validate_result({
            "overall_severity": "major",
            "summary": "ok",
            "comments": [
                {"path": "file.py", "body": "good comment"},  # valid
                {"body": "missing path"},                       # invalid — no path
                "not a dict",                                   # invalid type
            ],
        })
        assert len(result["comments"]) == 1
        assert result["comments"][0]["path"] == "file.py"

    @pytest.mark.asyncio
    async def test_review_calls_inference_api(self):
        with patch.dict("os.environ", {"HF_TOKEN": "hf_test123"}):
            reviewer = CodeReviewer()
            reviewer.client = AsyncMock()
            reviewer.client.text_generation = AsyncMock(return_value=SAMPLE_LLM_RESPONSE)

            result = await reviewer.review(SAMPLE_DIFF, pr_title="Fix SQL injection")

            assert result["overall_severity"] == "critical"
            assert len(result["comments"]) == 2
            reviewer.client.text_generation.assert_called_once()


class TestGitHubClient:
    def test_review_event_critical(self):
        from src.github_client import GitHubClient
        with patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_test"}):
            client = GitHubClient()
        assert client._review_event("critical") == "REQUEST_CHANGES"
        assert client._review_event("major") == "REQUEST_CHANGES"
        assert client._review_event("minor") == "COMMENT"
        assert client._review_event("info") == "COMMENT"

    def test_build_summary_body_contains_severity(self):
        from src.github_client import GitHubClient
        with patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_test"}):
            client = GitHubClient()
        review_result = {
            "overall_severity": "major",
            "summary": "Some issues found.",
            "comments": [
                {"severity": "major", "category": "correctness", "path": "f.py", "body": "x"},
                {"severity": "minor", "category": "style", "path": "f.py", "body": "y"},
            ],
        }
        body = client._build_summary_body(review_result)
        assert "MAJOR" in body
        assert "2 inline comment" in body

    def test_build_inline_comments(self):
        from src.github_client import GitHubClient
        with patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_test"}):
            client = GitHubClient()
        comments = [
            {"path": "app.py", "line": 10, "severity": "critical", "category": "security", "body": "Bad secret"},
        ]
        inline = client._build_inline_comments(comments)
        assert len(inline) == 1
        assert inline[0]["path"] == "app.py"
        assert inline[0]["line"] == 10
        assert "🔴" in inline[0]["body"]
        assert "Security" in inline[0]["body"]
