"""
alert_check.py — Part 3 bonus prototype

Loads the existing CSV, applies the three-condition virality alert from the
Part 3 alert design, and fires a Slack webhook if anything crosses threshold.

Thresholds are grounded in Part 2 findings:
  - score_per_hour > 250  : derived from the 6.7% viral rate in r/technology
                            and the observation that the 2.4% of posts that
                            crossed 1k score did so within the first 4 hours
  - upvote_ratio 0.75–0.95: the clean engagement band from Part 2 analysis
  - subreddit == technology: highest viral conversion rate in the dataset

This is a working prototype of one automated step — no new infrastructure
required beyond the Slack webhook secret already in the Actions workflow.
"""

import os
import json
import pandas as pd
import urllib.request

DATA_PATH = "data/reddit_data.csv"
SLACK_WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL")

# ── Thresholds from Part 2 ────────────────────────────────────────────────────
SCORE_PER_HOUR_THRESHOLD = 250       # top-velocity cutoff
UPVOTE_RATIO_MIN = 0.75              # bottom of the clean engagement band
UPVOTE_RATIO_MAX = 0.95              # above this = brigaded, not organic
MIN_COMMENTS = 20                    # filters out low-engagement noise


def check_alerts(df: pd.DataFrame) -> list[dict]:
    """
    Returns a list of alert dicts for posts that meet all three conditions.
    Empty list = nothing to fire.
    """
    if df.empty:
        return []

    # Only look at posts scraped in the last 2 hours (this run + last run)
    now = pd.Timestamp.utcnow().timestamp()
    recent = df[df["scraped_at_utc"] >= now - 7200].copy() if "scraped_at_utc" in df.columns else df.copy()

    alerts = recent[
        (recent["score_per_hour"] > SCORE_PER_HOUR_THRESHOLD) &
        (recent["upvote_ratio"] >= UPVOTE_RATIO_MIN) &
        (recent["upvote_ratio"] <= UPVOTE_RATIO_MAX) &
        (recent["num_comments"] >= MIN_COMMENTS)
    ].copy()

    return alerts.to_dict("records")


def format_slack_message(posts: list[dict]) -> str:
    lines = [f"🚨 *Virality Alert — {len(posts)} post(s) crossing threshold*\n"]
    for p in posts[:5]:   # cap at 5 to avoid Slack message overflow
        lines.append(
            f"• *{p['subreddit']}* | score: {p['score']} "
            f"| {p['score_per_hour']:.0f}/hr | ratio: {p['upvote_ratio']:.2f}\n"
            f"  <{p['url']}|{p['title'][:80]}>"
        )
    if len(posts) > 5:
        lines.append(f"\n_...and {len(posts) - 5} more_")
    return "\n".join(lines)


def fire_slack(message: str):
    if not SLACK_WEBHOOK:
        print("SLACK_WEBHOOK_URL not set — printing alert to stdout instead:")
        print(message)
        return

    payload = json.dumps({"text": message}).encode("utf-8")
    req = urllib.request.Request(
        SLACK_WEBHOOK,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        print(f"Slack webhook status: {resp.status}")


def main():
    if not os.path.exists(DATA_PATH):
        print(f"No dataset found at {DATA_PATH} — skipping alert check")
        return

    df = pd.read_csv(DATA_PATH)
    print(f"Alert check: {len(df)} total posts loaded")

    alerts = check_alerts(df)

    if not alerts:
        print("No posts crossing virality threshold — all quiet")
        return

    print(f"ALERT: {len(alerts)} posts crossing threshold")
    message = format_slack_message(alerts)
    fire_slack(message)


if __name__ == "__main__":
    main()