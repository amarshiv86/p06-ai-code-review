import json
import os
import re

import gradio as gr
from transformers import pipeline

# ── Model setup — runs locally inside the Space, no external API call ─────────
# Using a small model that fits in CPU RAM on free tier
MODEL = "Qwen/Qwen2.5-Coder-0.5B-Instruct"

print(f"Loading model {MODEL}...")
pipe = pipeline(
    "text-generation",
    model=MODEL,
    max_new_tokens=1024,
    temperature=0.1,
    do_sample=True,
    device_map="cpu",
)
print("Model loaded.")

SYSTEM_PROMPT = """You are a senior software engineer doing a code review.
Analyze the git diff and return ONLY valid JSON — no markdown fences, no explanation outside JSON.

JSON format:
{
  "overall_severity": "critical" | "major" | "minor" | "info",
  "summary": "2-3 sentence assessment",
  "comments": [
    {
      "path": "file.py",
      "line": 5,
      "severity": "critical" | "major" | "minor" | "info",
      "category": "security" | "performance" | "correctness" | "style" | "maintainability",
      "body": "Specific actionable feedback with suggested fix."
    }
  ]
}"""

SEVERITY_EMOJI = {"critical": "🔴", "major": "🟠", "minor": "🟡", "info": "🔵"}

SAMPLE_DIFF = '''diff --git a/auth.py b/auth.py
--- a/auth.py
+++ b/auth.py
@@ -1,10 +1,14 @@
+import os
 import sqlite3
+SECRET_KEY = "hardcoded_secret_abc123"
+
 def get_user(user_id):
-    conn = sqlite3.connect("prod.db")
-    cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")
+    conn = sqlite3.connect(os.getenv("DB_PATH", "prod.db"))
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
        raise ValueError(f"No JSON in response: {raw[:200]}")
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
        parts = []
        for c in comments:
            e = SEVERITY_EMOJI.get(c.get("severity", "info"), "🔵")
            parts.append(
                f"### {e} `{c.get('severity','info').upper()}` · {c.get('category','').title()}\n"
                f"**File:** `{c.get('path','?')}` · Line {c.get('line','?')}\n\n"
                f"{c.get('body','')}"
            )
        comments_md = "\n\n---\n\n".join(parts)
    return summary_md, comments_md


def run_review(diff: str, pr_title: str) -> tuple:
    if not diff.strip():
        return "⚠️ Please paste a git diff above.", "", ""
    try:
        prompt = (
            f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>\n"
            f"<|im_start|>user\nPR: {pr_title}\n\nDiff:\n{diff[:6000]}<|im_end|>\n"
            f"<|im_start|>assistant\n"
        )
        output = pipe(prompt, return_full_text=False)[0]["generated_text"]
        result = parse_response(output)
        summary_md, comments_md = format_output(result)
        return summary_md, comments_md, json.dumps(result, indent=2)
    except Exception as e:
        return f"❌ Error: {str(e)}", "", ""


# ── Gradio UI ──────────────────────────────────────────────────────────────────
with gr.Blocks(title="AI Code Review Bot", theme=gr.themes.Soft()) as demo:
    gr.Markdown("""
    # 🔍 AI Code Review Bot
    **P06 · Staff SRE + AI Engineer Portfolio**

    Paste a git diff to get an automated code review powered by **Qwen2.5-Coder 0.5B**
    running locally inside this Space (no external API calls).
    The production bot posts inline comments directly on GitHub PRs via webhook.

    > ⏳ First run may take 30-60s while the model loads.
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
    **Production bot architecture:**
    1. PR opened → GitHub Actions triggers webhook
    2. Bot fetches diff → sends to LLM → parses JSON
    3. Posts inline comments with severity labels on the PR

    [GitHub Repo](https://github.com/amarshiv86/p06-ai-code-review) ·
    [Staff SRE · AI Engineer Portfolio](https://github.com/amarshiv86)
    """)

demo.launch()
