# P06 · AI Code Review Bot

Automated pull request reviewer using **Mistral 7B** (HuggingFace Inference API) and **GitHub PR inline comments**. Part of the [Staff SRE · AI Engineer Portfolio](https://github.com/amarshiv86).

## Architecture

```
GitHub PR opened/updated
  → GitHub Actions (code-review.yml)
    → POST /webhook on the bot (running locally or on a server)
      → Fetch PR diff via GitHub API
      → Send diff to Mistral 7B via HF Inference API
      → Parse structured JSON (severity + per-line comments)
      → Post inline comments back to the PR
```

## Where things live

| What | Where |
|------|-------|
| Bot source code | This repo (`src/`) |
| Gradio demo UI | [HuggingFace Space](https://huggingface.co/spaces/amarshiv86/p06-ai-code-review) |
| Sample diffs + reviews | [HuggingFace Dataset](https://huggingface.co/datasets/amarshiv86/p06-code-review-dataset) |

## SRE additions

- HMAC-SHA256 webhook signature verification
- `/health` endpoint for uptime monitoring (ping with UptimeRobot)
- Structured logging with per-review latency tracking
- Severity → GitHub review event mapping (`REQUEST_CHANGES` vs `COMMENT`)
- Graceful error handling — failures return 500 without crashing the server

## Local setup

```bash
git clone https://github.com/amarshiv86/p06-ai-code-review
cd p06-ai-code-review
pip install -r requirements.txt
cp .env.example .env        # fill in your tokens
uvicorn src.main:app --reload --port 8000

# expose to GitHub webhooks:
ngrok http 8000
# copy the https URL into your GitHub repo webhook settings
```

## Run tests

```bash
pytest tests/ -v
```

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GITHUB_TOKEN` | Yes | PAT with `repo` + `pull-requests` write scope |
| `GITHUB_WEBHOOK_SECRET` | Recommended | HMAC secret — set same value in GitHub webhook settings |
| `HF_TOKEN` | Yes | HuggingFace token (free account, no billing required) |
| `HF_MODEL` | No | Model ID (default: `mistralai/Mistral-7B-Instruct-v0.3`) |
| `MAX_DIFF_CHARS` | No | Max diff chars sent to model (default: `12000`) |

## GitHub secrets needed

Add these in your GitHub repo → Settings → Secrets:
- `HF_TOKEN` — for the deploy workflows
- `CODE_REVIEW_BOT_URL` — the URL where your bot is running (e.g. ngrok or a server)

## Stack

`FastAPI` · `HuggingFace Inference API` · `Mistral 7B` · `GitHub API` · `Gradio` · `GitHub Actions`
