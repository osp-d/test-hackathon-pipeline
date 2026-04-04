import requests
import pandas as pd
import time
from datetime import datetime

HEADERS = {"User-Agent": "Mozilla/5.0 (research project)"}

AI_KEYWORDS = [
    "claude", "chatgpt", "openai", "anthropic",
    "llm", "gpt", "gemini", "ai", "llama"
]

# ─── COMMENTS ────────────────────────────────────────────────────────────────

def fetch_comments(post_url, post_created_utc):
    try:
        r = requests.get(
            post_url + ".json",
            headers=HEADERS,
            params={"sort": "top", "limit": 10},
            timeout=10
        )
        if r.status_code != 200:
            return []

        data = r.json()
        comments_data = data[1]["data"]["children"]
        comments = []

        for c in comments_data:
            d = c.get("data", {})
            body = d.get("body", "")

            if not body or body in ("[deleted]", "[removed]"):
                is_deleted = True
                body = ""
            else:
                is_deleted = False

            comment_created = d.get("created_utc", 0)
            minutes_after = round(
                (comment_created - post_created_utc) / 60, 1
            ) if comment_created and post_created_utc else None

            dt = datetime.utcfromtimestamp(comment_created) if comment_created else None

            comments.append({
                "comment_id":           d.get("id"),
                "post_url":             post_url,
                "author":               d.get("author"),
                "author_flair":         d.get("author_flair_text") or "",
                "body":                 body,
                "depth":                d.get("depth", 0),
                "is_submitter":         d.get("is_submitter", False),
                "score":                d.get("score", 0),
                "controversiality":     d.get("controversiality", 0),
                "gilded":               d.get("gilded", 0),
                "total_awards":         d.get("total_awards_received", 0),
                "distinguished":        d.get("distinguished") or "",
                "is_deleted":           is_deleted,
                "is_mod_removed":       d.get("removed", False),
                "created_utc":          comment_created,
                "created_date":         dt.strftime("%Y-%m-%d") if dt else None,
                "created_hour":         dt.hour if dt else None,
                "minutes_after_post":   minutes_after,
            })

        return comments

    except Exception as e:
        print(f"  Comment error: {e}")
        return []


# ─── AUTHOR HISTORY ───────────────────────────────────────────────────────────

def fetch_author(username):
    empty = {
        "author":               username,
        "account_age_days":     None,
        "total_posts_sampled":  None,
        "ai_post_ratio":        None,
        "claude_post_ratio":    None,
        "subreddit_diversity":  None,
        "avg_score":            None,
        "posting_frequency":    None,
    }

    if not username or username == "[deleted]":
        return empty

    try:
        r = requests.get(
            f"https://www.reddit.com/user/{username}/submitted.json",
            headers=HEADERS,
            params={"limit": 25},
            timeout=10
        )
        if r.status_code != 200:
            return empty

        posts = r.json()["data"]["children"]
        if not posts:
            return empty

        total = len(posts)
        scores = [p["data"].get("score", 0) for p in posts]
        subreddits = [p["data"].get("subreddit", "") for p in posts]
        titles = [p["data"].get("title", "").lower() for p in posts]
        timestamps = [p["data"].get("created_utc", 0) for p in posts]

        ai_count = sum(
            1 for t in titles
            if any(kw in t for kw in AI_KEYWORDS)
        )
        claude_count = sum(1 for t in titles if "claude" in t)

        oldest = min(timestamps)
        newest = max(timestamps)
        age_days = round((time.time() - oldest) / 86400)
        span_weeks = max((newest - oldest) / 604800, 1)

        return {
            "author":               username,
            "account_age_days":     age_days,
            "total_posts_sampled":  total,
            "ai_post_ratio":        round(ai_count / total, 2),
            "claude_post_ratio":    round(claude_count / total, 2),
            "subreddit_diversity":  len(set(subreddits)),
            "avg_score":            round(sum(scores) / total, 1),
            "posting_frequency":    round(total / span_weeks, 2),
        }

    except Exception as e:
        print(f"  Author error ({username}): {e}")
        return empty


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    df = pd.read_csv("data/reddit_data.csv")

    # ── Comments: top 200 posts by score only ──
    top_posts = df.nlargest(200, "score")[["url", "created_utc"]].drop_duplicates()
    print(f"Fetching comments for top {len(top_posts)} posts...")

    all_comments = []
    for i, row in enumerate(top_posts.itertuples(), 1):
        print(f"  [{i}/{len(top_posts)}] {row.url[:60]}")
        comments = fetch_comments(row.url, row.created_utc)
        all_comments.extend(comments)
        time.sleep(0.5)

    comments_df = pd.DataFrame(all_comments)
    comments_df.to_csv("reddit_comments.csv", index=False)
    print(f"  → {len(comments_df)} comments saved to reddit_comments.csv\n")

    # ── Authors: top 100 posts, unique authors only ──
    top_authors = (
        df.nlargest(100, "score")["author"]
        .dropna()
        .unique()
    )
    top_authors = [a for a in top_authors if a != "[deleted]"]
    print(f"Fetching author history for {len(top_authors)} authors...")

    all_authors = []
    for i, username in enumerate(top_authors, 1):
        print(f"  [{i}/{len(top_authors)}] u/{username}")
        author_data = fetch_author(username)
        all_authors.append(author_data)
        time.sleep(0.5)

    authors_df = pd.DataFrame(all_authors)
    authors_df.to_csv("reddit_authors.csv", index=False)
    print(f"  → {len(authors_df)} authors saved to reddit_authors.csv")

    # ── Summary ──
    print("\n" + "=" * 60)
    print("ENRICHMENT DONE")
    print(f"  reddit_comments.csv — {len(comments_df)} rows")
    print(f"  reddit_authors.csv  — {len(authors_df)} rows")
    if len(comments_df):
        fast = comments_df[comments_df["minutes_after_post"] < 5]
        print(f"  Comments within 5min of post: {len(fast)} ({round(100*len(fast)/len(comments_df))}%)")
    if len(authors_df):
        sus = authors_df[authors_df["claude_post_ratio"] > 0.5]
        print(f"  Authors with >50% Claude posts: {len(sus)}")
    print("=" * 60)


if __name__ == "__main__":
    main()