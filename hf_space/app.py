import json
import os
import re

import gradio as gr
import requests

# ── Model setup ───────────────────────────────────────────────────────────────
HF_TOKEN = os.environ.get("HF_TOKEN")

# Qwen2.5-Coder is confirmed working on HF free tier via direct HTTP
MODEL = "Qwen/Qwen2.5-Coder-7B-Instruct"
API_URL = f"https://api-inference.huggingface.co/models/{MODEL}/v1/chat/completions"

SYSTEM_PROMPT = """You are a senior software engineer performing a code review.
Analyze the provided git diff and return ONLY a JSON object — no markdown, no preamble.

JSON schema:
{
  "overall_severity": "critical" | "major" | "minor" | "info",
  "summary": "2-3 sentence overall assessment",
  "comments": [
    {
      "path": "file/path.py",
      "line": <integer line number>,
      "severity": "critical" | "major" | "minor" | "info",
      "category": "security" | "performance" | "correctness" | "style" | "maintainability",
      "body": "Specific actionable feedback with suggested fix."
    }
  ]
}

Severity guide: critical=security/crash risk, major=logic bug, minor=code smell, info=suggestion.
Return valid JSON only. No explanation outside the JSON."""

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


def call_llm(diff: str, pr_title: str) -> str:
    """Call HF Inference API via direct HTTP — works on free tier."""
    headers = {
        "Authorization": f"Bearer {HF_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"PR Title: {pr_title}\n\nGit diff:\n```\n{diff[:8000]}\n```"},
        ],
        "max_tokens": 1500,
        "temperature": 0.1,
        "stream": False,
    }
    resp = requests.post(API_URL, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def parse_response(raw: str) -> dict:
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON found. Model returned:\n{raw[:300]}")
    return json.loads(match.group())


def format_output(result: dict) -> tuple:
    severity = result.get("overall_severity", "info")
    emoji = SEVERITY_EMOJI.get(severity, "🔵")
    summary_md = (
        f"## {emoji} Overall: `{severity.upper()}`\n\n"
        f"{result.get('summary', '')}\n\n"
        f"**{len(result.get('comments', []))} inline comment(s) found**"
    )
    comments = result.get("comments", [])
    if not comments:
        comments_md = "_No specific inline comments._"
    else:
        lines = []
        for c in comments:
            e = SEVERITY_EMOJI.get(c.get("severity", "info"), "🔵")
            lines.append(
                f"### {e} `{c.get('severity','info').upper()}` · {c.get('category','').title()}\n"
                f"**File:** `{c.get('path','?')}` · Line {c.get('line','?')}\n\n"
                f"{c.get('body','')}"
            )
        comments_md = "\n\n---\n\n".join(lines)
    return summary_md, comments_md


def run_review(diff: str, pr_title: str) -> tuple:
    if not diff.strip():
        return "⚠️ Please paste a git diff above.", "", ""
    if not HF_TOKEN:
        return "⚠️ HF_TOKEN secret not set in Space Settings → Repository secrets.", "", ""
    try:
        raw = call_llm(diff, pr_title)
        result = parse_response(raw)
        summary_md, comments_md = format_output(result)
        return summary_md, comments_md, json.dumps(result, indent=2)
    except requests.HTTPError as e:
        return f"❌ API Error {e.response.status_code}: {e.response.text[:300]}", "", ""
    except Exception as e:
        return f"❌ Error: {str(e)}", "", ""


# ── Gradio UI ──────────────────────────────────────────────────────────────────
with gr.Blocks(title="AI Code Review Bot", theme=gr.themes.Soft()) as demo:
    gr.Markdown("""
    # 🔍 AI Code Review Bot
    **P06 · Staff SRE + AI Engineer Portfolio**

    Paste a git diff to get an automated code review powered by **Qwen2.5-Coder 7B**
    (HuggingFace Inference API · free tier). The production bot posts inline comments
    directly on GitHub PRs via webhook.
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
    3. Bot fetches the diff → sends to LLM → parses structured JSON
    4. Posts inline comments with severity labels directly on the PR

    [GitHub Repo](https://github.com/amarshiv86/p06-ai-code-review) ·
    [Staff SRE · AI Engineer Portfolio](https://github.com/amarshiv86)
    """)

demo.launch()
