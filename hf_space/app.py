import json
import os
import re

import gradio as gr
from huggingface_hub import InferenceClient

# ── Model setup ───────────────────────────────────────────────────────────────
HF_TOKEN = os.environ.get("HF_TOKEN")
MODEL = os.environ.get("HF_MODEL", "mistralai/Mistral-7B-Instruct-v0.3")

client = InferenceClient(token=HF_TOKEN)

SYSTEM_PROMPT = """You are a senior software engineer performing a code review.
Analyze the provided git diff and return ONLY a JSON object — no markdown, no explanation outside the JSON.

JSON schema:
{
  "overall_severity": "critical" | "major" | "minor" | "info",
  "summary": "2-3 sentence overall assessment",
  "comments": [
    {
      "path": "file/path.py",
      "line": <line number>,
      "severity": "critical" | "major" | "minor" | "info",
      "category": "security" | "performance" | "correctness" | "style" | "maintainability",
      "body": "Specific actionable feedback with suggested fix."
    }
  ]
}

Severity: critical=security/crash, major=logic bug, minor=code smell, info=suggestion.
Return valid JSON only."""

SEVERITY_EMOJI = {"critical": "🔴", "major": "🟠", "minor": "🟡", "info": "🔵"}

SAMPLE_DIFF = '''diff --git a/auth.py b/auth.py
index 1234567..abcdefg 100644
--- a/auth.py
+++ b/auth.py
@@ -1,12 +1,16 @@
+import os
 import sqlite3

+SECRET_KEY = "hardcoded_secret_abc123"
+
 def get_user(user_id):
-    conn = sqlite3.connect("prod.db")
-    cursor = conn.cursor()
-    cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")
+    conn = sqlite3.connect(os.getenv("DB_PATH", "prod.db"))
+    cursor = conn.cursor()
+    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
     return cursor.fetchone()

 def check_password(plain, hashed):
-    return plain == hashed
+    import hashlib
+    return hashlib.sha256(plain.encode()).hexdigest() == hashed
'''


def parse_response(raw: str) -> dict:
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError("No JSON found in model response")
    return json.loads(match.group())


def format_output(result: dict) -> tuple:
    severity = result.get("overall_severity", "info")
    emoji = SEVERITY_EMOJI.get(severity, "🔵")

    summary_md = f"""## {emoji} Overall: `{severity.upper()}`

{result.get('summary', '')}

**{len(result.get('comments', []))} inline comment(s) found**
"""

    if not result.get("comments"):
        comments_md = "_No specific inline comments._"
    else:
        lines = []
        for c in result["comments"]:
            e = SEVERITY_EMOJI.get(c.get("severity", "info"), "🔵")
            lines.append(
                f"### {e} `{c.get('severity','info').upper()}` · {c.get('category','').title()}\n"
                f"**File:** `{c.get('path', '?')}` · Line {c.get('line', '?')}\n\n"
                f"{c.get('body', '')}\n"
            )
        comments_md = "\n---\n".join(lines)

    return summary_md, comments_md


def run_review(diff: str, pr_title: str) -> tuple:
    if not diff.strip():
        return "⚠️ Please paste a git diff above.", "", ""

    if not HF_TOKEN:
        return "⚠️ HF_TOKEN secret not set in Space settings.", "", ""

    try:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"PR Title: {pr_title}\n\nGit diff:\n```\n{diff[:10000]}\n```"},
        ]

        response = client.chat_completion(
            messages=messages,
            model=MODEL,
            max_tokens=2048,
            temperature=0.1,
        )
        raw = response.choices[0].message.content
        result = parse_response(raw)
        summary_md, comments_md = format_output(result)
        raw_json = json.dumps(result, indent=2)
        return summary_md, comments_md, raw_json

    except Exception as e:
        return f"❌ Error: {str(e)}", "", ""


# ── Gradio UI ─────────────────────────────────────────────────────────────────
with gr.Blocks(title="AI Code Review Bot", theme=gr.themes.Soft()) as demo:
    gr.Markdown("""
    # 🔍 AI Code Review Bot
    **P06 · Staff SRE + AI Engineer Portfolio**

    Paste a git diff to get an automated code review powered by **Mistral 7B** (HuggingFace Inference API).
    The production version of this bot posts inline comments directly on GitHub PRs via webhook.
    """)

    with gr.Row():
        with gr.Column(scale=2):
            pr_title = gr.Textbox(
                label="PR Title (optional)",
                placeholder="Fix SQL injection vulnerability in auth module",
            )
            diff_input = gr.Textbox(
                label="Git Diff",
                placeholder="Paste your git diff here...",
                lines=18,
                value=SAMPLE_DIFF,
            )
            with gr.Row():
                submit_btn = gr.Button("🔍 Review Code", variant="primary")
                clear_btn = gr.Button("Clear")

        with gr.Column(scale=3):
            summary_out = gr.Markdown(label="Summary")
            comments_out = gr.Markdown(label="Inline Comments")
            with gr.Accordion("Raw JSON output", open=False):
                json_out = gr.Code(language="json", label="Structured output")

    submit_btn.click(
        fn=run_review,
        inputs=[diff_input, pr_title],
        outputs=[summary_out, comments_out, json_out],
    )
    clear_btn.click(
        fn=lambda: ("", "", "", ""),
        outputs=[diff_input, pr_title, summary_out, comments_out],
    )

    gr.Markdown("""
    ---
    **How the production bot works:**
    1. Developer opens a PR on GitHub
    2. GitHub Actions triggers the webhook bot
    3. Bot fetches the diff, sends to Mistral 7B, parses structured JSON
    4. Posts inline comments with severity labels directly on the PR

    [GitHub Repo](https://github.com/amarshiv86/p06-ai-code-review) · Part of the [Staff SRE · AI Engineer Portfolio](https://github.com/amarshiv86)
    """)

demo.launch()
