"""
alert_check.py — Part 3 bonus prototype (Telegram notifications)

Sits at repo root. Reads data/reddit_data.csv and fires a Telegram
message when a post crosses the virality threshold from Part 2.

Secrets required (repo Settings → Secrets → Actions):
  TELEGRAM_BOT_TOKEN  — from @BotFather
  TELEGRAM_CHAT_ID    — your personal chat ID or a group/channel ID

To get your chat ID:
  1. Message your bot once (it can't initiate)
  2. curl https://api.telegram.org/bot<TOKEN>/getUpdates
  3. Copy the "id" field from the "chat" object

Thresholds grounded in Part 2 findings:
  score_per_hour > 250  — derived from 6.7% viral rate in r/technology
                          and the observation that posts crossing 1k score
                          (2.4% of total) did so within the first 4 hours
  upvote_ratio 0.75–0.95 — the clean organic engagement band from Part 2
  num_comments >= 20    — filters low-engagement noise
"""

import os
import json
import urllib.request
import pandas as pd

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "reddit_data.csv")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# ── Thresholds from Part 2 ────────────────────────────────────────────────────
SCORE_PER_HOUR_THRESHOLD = 250
UPVOTE_RATIO_MIN = 0.75
UPVOTE_RATIO_MAX = 0.95
MIN_COMMENTS = 20


def check_alerts(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []

    # Only consider posts scraped in the last 2 hours (this run + previous run)
    if "scraped_at_utc" in df.columns:
        now = pd.Timestamp.utcnow().timestamp()
        df = df[df["scraped_at_utc"] >= now - 7200].copy()

    alerts = df[
        (df["score_per_hour"] > SCORE_PER_HOUR_THRESHOLD) &
        (df["upvote_ratio"] >= UPVOTE_RATIO_MIN) &
        (df["upvote_ratio"] <= UPVOTE_RATIO_MAX) &
        (df["num_comments"] >= MIN_COMMENTS)
    ]

    return alerts.to_dict("records")


def format_telegram_message(posts: list[dict]) -> str:
    lines = [f"🚨 <b>Virality Alert — {len(posts)} post(s) crossing threshold</b>\n"]
    for p in posts[:5]:
        title = p["title"][:80] + ("…" if len(p["title"]) > 80 else "")
        lines.append(
            f"• <b>r/{p['subreddit']}</b> | "
            f"score: {p['score']} | "
            f"{p['score_per_hour']:.0f}/hr | "
            f"ratio: {p['upvote_ratio']:.2f}\n"
            f'  <a href="{p["url"]}">{title}</a>'
        )
    if len(posts) > 5:
        lines.append(f"\n<i>…and {len(posts) - 5} more</i>")
    return "\n".join(lines)


def send_telegram(message: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        # No credentials — print to stdout so the Actions log still shows it
        print("Telegram credentials not set. Alert (stdout fallback):")
        print(message)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        print(f"Telegram response: {resp.status}")


def main():
    if not os.path.exists(DATA_PATH):
        print(f"No dataset at {DATA_PATH} — skipping alert check")
        return

    df = pd.read_csv(DATA_PATH)
    print(f"Alert check: {len(df)} total posts loaded")

    alerts = check_alerts(df)

    if not alerts:
        print("No posts crossing virality threshold — all quiet")
        return

    print(f"ALERT: {len(alerts)} post(s) crossing threshold")
    message = format_telegram_message(alerts)
    send_telegram(message)


if __name__ == "__main__":
    main()