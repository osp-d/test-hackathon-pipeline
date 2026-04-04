import asyncio
import time
import aiohttp
import pandas as pd
from datetime import datetime
import os

HEADERS = headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

TIER2_SUBREDDITS = [
    "ClaudeAI", "ChatGPT", "artificial",
    "singularity", "LocalLLaMA", "MachineLearning", "OpenAI",
]

TIER2_QUERIES = [
    "Claude vs ChatGPT", "Claude vs GPT-4", "Claude vs Gemini",
    "switched to Claude", "moved from ChatGPT to Claude",
    "Claude wrote", "Claude built", "Claude generated",
    "Claude helped me", "Claude just",
    "Claude AI amazing", "Claude AI better",
    "Claude AI failed", "Claude refused", "Claude AI worse",
    "disappointed with Claude",
    "Anthropic Claude", "Claude 3", "Claude Opus",
    "Claude Sonnet", "Claude Haiku", "Claude 3.5",
    "Claude for coding", "Claude for writing",
    "Claude API", "Claude system prompt", "Claude jailbreak",
]

TIER1_SUBREDDITS = [
    "technology", "programming", "Futurology",
    "productivity", "Entrepreneur", "startups",
    "datascience", "webdev", "ArtificialInteligence",
]

TIER1_QUERIES = [
    "Claude AI", "Anthropic Claude", "Claude vs ChatGPT",
]

CORE_KEYWORDS = ["claude", "anthropic"]
CLAUDE_LAUNCH_UTC = 1677628800
CONCURRENCY = 5

# FIX 1: time_filter controls history depth.
# "hour" → only posts from the last hour  (scheduled/alert runs)
# "day"  → last 24 h                      (daily digest)
# "all"  → full history                   (initial backfill only)
TIME_FILTER = os.environ.get("TIME_FILTER", "hour")

# Script lives in scrapers/, data lives in data/ at repo root
DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "reddit_data.csv")


def is_relevant(title, body):
    text = (title + " " + (body or "")).lower()
    return any(kw in text for kw in CORE_KEYWORDS)


def parse_post(p, query, tier):
    title = p.get("title", "")
    body = p.get("selftext", "") or ""

    if not is_relevant(title, body):
        return None

    created = p.get("created_utc", 0)
    if created < CLAUDE_LAUNCH_UTC:
        return None

    score = p.get("score", 0)
    if score <= 0:
        return None

    dt = datetime.utcfromtimestamp(created)
    num_comments = p.get("num_comments", 1)
    upvote_ratio = p.get("upvote_ratio", 1)

    return {
        "platform": "reddit",
        "tier": tier,
        "subreddit": p.get("subreddit"),
        "title": title,
        "body": body,
        "author": p.get("author"),
        "url": "https://reddit.com" + p.get("permalink", ""),
        "domain": p.get("domain") or "self",
        "flair": p.get("link_flair_text") or "",
        "is_self": p.get("is_self"),
        "query_used": query,
        "created_utc": created,
        "created_date": dt.strftime("%Y-%m-%d"),
        "created_hour": dt.hour,
        "day_of_week": dt.strftime("%A"),
        "month": dt.strftime("%Y-%m"),
        "score": score,
        "upvote_ratio": upvote_ratio,
        "num_comments": num_comments,
        "score_per_comment": round(score / max(num_comments, 1), 2),
        "upvote_ratio_bucket": (
            "controversial" if upvote_ratio < 0.6
            else "contested" if upvote_ratio < 0.75
            else "clean"
        ),
        "engagement_bucket": (
            "viral" if score > 5000
            else "high" if score > 1000
            else "mid" if score > 100
            else "low"
        ),
        "total_awards": p.get("total_awards_received", 0),
        "gilded": p.get("gilded", 0),
        "crosspost_count": p.get("num_crossposts", 0),
        "is_crosspost": bool(p.get("crosspost_parent")),
        "hours_old": round((time.time() - created) / 3600, 1),
        "score_per_hour": round(score / max((time.time() - created) / 3600, 1), 2),
        "author_is_deleted": p.get("author") == "[deleted]",
        "author_flair": p.get("author_flair_text") or "",
        "is_video": p.get("is_video", False),
        "is_gallery": p.get("is_gallery", False),
        "post_hint": p.get("post_hint", ""),
        "has_image": p.get("url", "").endswith((".jpg", ".png", ".gif", ".jpeg")),
        "is_stickied": p.get("stickied", False),
        "scraped_at_utc": int(time.time()),
    }


# FIX 2: exponential backoff — retries instead of returning None on 429
async def fetch_page(session, semaphore, url, params, retries=3):
    async with semaphore:
        for attempt in range(retries):
            try:
                async with session.get(
                    url, params=params,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as r:
                    if r.status == 429:
                        wait = 2 ** (attempt + 1)   # 2s → 4s → 8s
                        print(f"  Rate limited — backoff {wait}s (attempt {attempt+1}/{retries})")
                        await asyncio.sleep(wait)
                        continue
                    if r.status != 200:
                        print(f"  HTTP {r.status} — skipping")
                        return None
                    return await r.json()
            except Exception as e:
                wait = 2 ** (attempt + 1)
                print(f"  Error: {e} — backoff {wait}s")
                await asyncio.sleep(wait)
        print(f"  Gave up after {retries} retries")
        return None


async def search_reddit(session, semaphore, subreddit, query, tier, limit=100):
    url = f"https://www.reddit.com/r/{subreddit}/search.json"
    params = {
        "q": query,
        "sort": "new",        # "new" surfaces fresh posts; "relevance" buries them
        "t": TIME_FILTER,     # FIX 1: controlled by env var
        "limit": 100,
        "restrict_sr": "true",
    }

    posts = []
    after = None

    while len(posts) < limit:
        if after:
            params["after"] = after

        data = await fetch_page(session, semaphore, url, params)
        if not data:
            break

        children = data["data"].get("children", [])
        if not children:
            break

        for item in children:
            parsed = parse_post(item["data"], query, tier)
            if parsed:
                posts.append(parsed)

        after = data["data"].get("after")
        if not after:
            break

        await asyncio.sleep(0.5)

    return posts


async def run_tier(session, semaphore, subreddits, queries, tier, label):
    tasks = [
        search_reddit(session, semaphore, subreddit, query, tier)
        for subreddit in subreddits
        for query in queries
    ]
    total = len(tasks)
    print(f"  {total} queries (max {CONCURRENCY} concurrent, TIME_FILTER={TIME_FILTER})")

    all_posts = []
    for i, coro in enumerate(asyncio.as_completed(tasks), 1):
        posts = await coro
        all_posts.extend(posts)
        print(f"  [{label}] {i}/{total} — {len(posts)} posts")

    return all_posts


# FIX 3: append-and-deduplicate instead of overwrite
def save_with_dedup(new_df, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)

    if os.path.exists(path):
        existing = pd.read_csv(path)
        combined = pd.concat([existing, new_df], ignore_index=True)
    else:
        combined = new_df

    combined.sort_values("score", ascending=False, inplace=True)
    combined.drop_duplicates(subset="url", keep="first", inplace=True)
    combined.drop_duplicates(subset="title", keep="first", inplace=True)
    combined.reset_index(drop=True, inplace=True)
    combined.to_csv(path, index=False)
    return combined


async def main():
    semaphore = asyncio.Semaphore(CONCURRENCY)

    async with aiohttp.ClientSession(headers=HEADERS) as session:
        print("=" * 60)
        print(f"Scrape run — TIME_FILTER={TIME_FILTER}")
        print("=" * 60)

        print("\nTier 1 — broad subreddits")
        tier1_posts = await run_tier(
            session, semaphore, TIER1_SUBREDDITS, TIER1_QUERIES, tier=1, label="T1"
        )

        print("\nTier 2 — AI subreddits")
        tier2_posts = await run_tier(
            session, semaphore, TIER2_SUBREDDITS, TIER2_QUERIES, tier=2, label="T2"
        )

    new_df = pd.DataFrame(tier1_posts + tier2_posts)
    if new_df.empty:
        print("No new posts this run.")
        return

    combined = save_with_dedup(new_df, DATA_PATH)

    print("\n" + "=" * 60)
    print(f"Run complete — {len(new_df)} new posts | {len(combined)} total after dedup")
    print(f"  Viral (>5000):       {len(combined[combined['engagement_bucket']=='viral'])}")
    print(f"  score_per_hour >250: {len(combined[combined['score_per_hour']>250])}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())