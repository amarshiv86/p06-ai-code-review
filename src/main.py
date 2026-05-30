import hashlib
import hmac
import logging
import os
import time

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from .github_client import GitHubClient
from .reviewer import CodeReviewer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="AI Code Review Bot",
    description="Webhook receiver — triggered by GitHub Actions on every PR",
    version="1.0.0",
)

reviewer = CodeReviewer()
github = GitHubClient()

_stats = {"reviews_run": 0, "start_time": time.time()}


def verify_github_signature(payload: bytes, signature: str) -> bool:
    secret = os.environ.get("WEBHOOK_SECRET", "")
    if not secret:
        logger.warning("WEBHOOK_SECRET not set — skipping verification")
        return True
    expected = "sha256=" + hmac.new(
        secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@app.get("/health")
async def health():
    """Health check — ping this with UptimeRobot to keep the bot warm."""
    return {
        "status": "ok",
        "uptime_minutes": round((time.time() - _stats["start_time"]) / 60, 1),
        "reviews_run": _stats["reviews_run"],
    }


@app.post("/webhook")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(None),
    x_hub_signature_256: str = Header(None),
):
    payload_bytes = await request.body()

    if x_hub_signature_256 and not verify_github_signature(payload_bytes, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    if x_github_event != "pull_request":
        return JSONResponse({"status": "ignored", "event": x_github_event})

    payload = await request.json()
    action = payload.get("action")

    if action not in ("opened", "synchronize", "reopened"):
        return JSONResponse({"status": "ignored", "action": action})

    pr = payload["pull_request"]
    repo_full_name = payload["repository"]["full_name"]
    pr_number = pr["number"]
    head_sha = pr["head"]["sha"]

    logger.info(f"Reviewing PR #{pr_number} on {repo_full_name}")
    start_time = time.time()

    try:
        diff = await github.get_pr_diff(repo_full_name, pr_number)
        review_result = await reviewer.review(diff, pr_title=pr.get("title", ""))
        await github.post_review(
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            head_sha=head_sha,
            review_result=review_result,
        )

        elapsed = round(time.time() - start_time, 2)
        _stats["reviews_run"] += 1
        logger.info(f"Done in {elapsed}s — {len(review_result['comments'])} comments")

        return JSONResponse({
            "status": "reviewed",
            "pr": pr_number,
            "comments_posted": len(review_result["comments"]),
            "overall_severity": review_result["overall_severity"],
            "elapsed_seconds": elapsed,
        })

    except Exception as e:
        logger.error(f"Review failed for PR #{pr_number}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
