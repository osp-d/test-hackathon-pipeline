import asyncio
import time
import aiohttp
import pandas as pd
from datetime import datetime

HEADERS = {"User-Agent": "Mozilla/5.0 (research project)"}

TIER2_SUBREDDITS = [
    "ClaudeAI", "ChatGPT", "artificial",
    "singularity", "LocalLLaMA", "MachineLearning", "OpenAI",
]

TIER2_QUERIES = [
    # Comparisons
    "Claude vs ChatGPT", "Claude vs GPT-4", "Claude vs Gemini",
    "switched to Claude", "moved from ChatGPT to Claude",
    # Capability showcases
    "Claude wrote", "Claude built", "Claude generated",
    "Claude helped me", "Claude just",
    # Emotional/reaction
    "Claude AI amazing", "Claude AI better",
    "Claude AI failed", "Claude refused", "Claude AI worse",
    "disappointed with Claude",
    # Brand/announcements
    "Anthropic Claude", "Claude 3", "Claude Opus",
    "Claude Sonnet", "Claude Haiku", "Claude 3.5",
    # Use cases
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

# FIX 2: Require at least one of these core terms in the text.
# "haiku/sonnet/opus/llm/chatbot" alone are too broad and cause false positives
# (e.g. Claude Shannon, generic LLM posts with no Claude mention).
CORE_KEYWORDS = ["claude", "anthropic"]

# FIX 2: Claude was first released in March 2023 — anything older is a false positive.
CLAUDE_LAUNCH_UTC = 1677628800  # 2023-03-01 00:00:00 UTC

# Max concurrent requests — keep low to avoid 429s
CONCURRENCY = 5


def is_relevant(title, body):
    text = (title + " " + (body or "")).lower()
    # FIX 2: Must contain a core keyword, not just secondary terms
    return any(kw in text for kw in CORE_KEYWORDS)


def parse_post(p, query, tier):
    title = p.get("title", "")
    body = p.get("selftext", "") or ""

    if not is_relevant(title, body):
        return None

    created = p.get("created_utc", 0)

    # FIX 2: Drop pre-Claude-era posts at parse time
    if created < CLAUDE_LAUNCH_UTC:
        return None

    score = p.get("score", 0)

    # FIX 3: Drop zero-score posts at parse time — they are removed/deleted/spam
    if score <= 0:
        return None

    dt = datetime.utcfromtimestamp(created)
    num_comments = p.get("num_comments", 1)
    upvote_ratio = p.get("upvote_ratio", 1)

    return {
        # --- existing fields ---
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

        # --- awards ---
        "total_awards": p.get("total_awards_received", 0),
        "gilded": p.get("gilded", 0),

        # --- crosspost signals ---
        "crosspost_count": p.get("num_crossposts", 0),
        "is_crosspost": bool(p.get("crosspost_parent")),

        # --- velocity ---
        "hours_old": round((time.time() - created) / 3600, 1),
        "score_per_hour": round(score / max((time.time() - created) / 3600, 1), 2),

        # --- author signals ---
        "author_is_deleted": p.get("author") == "[deleted]",
        "author_flair": p.get("author_flair_text") or "",

        # --- content type ---
        "is_video": p.get("is_video", False),
        "is_gallery": p.get("is_gallery", False),
        "post_hint": p.get("post_hint", ""),
        "has_image": p.get("url", "").endswith((".jpg", ".png", ".gif", ".jpeg")),

        # --- visibility signals ---
        "is_stickied": p.get("stickied", False),
        # FIX 4: 'distinguished' dropped — was 99.8% null and carries no signal
    }


async def fetch_page(session, semaphore, url, params):
    async with semaphore:
        try:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 429:
                    print("  Rate limited — sleeping 30s")
                    await asyncio.sleep(30)
                    return None
                if r.status != 200:
                    print(f"  HTTP {r.status} — skipping")
                    return None
                return await r.json()
        except Exception as e:
            print(f"  Error: {e}")
            return None


async def search_reddit(session, semaphore, subreddit, query, tier, limit=250):
    url = f"https://www.reddit.com/r/{subreddit}/search.json"
    params = {
        "q": query,
        "sort": "relevance",
        "t": "all",
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
    print(f"  Running {total} queries concurrently (max {CONCURRENCY} at once)...")

    all_posts = []
    for i, coro in enumerate(asyncio.as_completed(tasks), 1):
        posts = await coro
        all_posts.extend(posts)
        print(f"  [{label}] {i}/{total} done — {len(posts)} posts")

    return all_posts


async def main():
    semaphore = asyncio.Semaphore(CONCURRENCY)

    async with aiohttp.ClientSession(headers=HEADERS) as session:
        print("=" * 60)
        print("Starting Tier 1 — broad subreddits, core queries")
        print("=" * 60)
        tier1_posts = await run_tier(
            session, semaphore,
            TIER1_SUBREDDITS, TIER1_QUERIES,
            tier=1, label="T1"
        )

        print("\n" + "=" * 60)
        print("Starting Tier 2 — core AI subreddits, all queries")
        print("=" * 60)
        tier2_posts = await run_tier(
            session, semaphore,
            TIER2_SUBREDDITS, TIER2_QUERIES,
            tier=2, label="T2"
        )

    all_posts = tier1_posts + tier2_posts
    df = pd.DataFrame(all_posts)

    # FIX 1: Deduplicate by title, keeping the highest-score copy.
    # URL dedup alone misses the same story crossposted across subreddits.
    df.drop_duplicates(subset="url", inplace=True)
    df.sort_values("score", ascending=False, inplace=True)
    df.drop_duplicates(subset="title", keep="first", inplace=True)  # <-- added

    df.reset_index(drop=True, inplace=True)
    df.to_csv("data/reddit_data.csv", index=False)

    print("\n" + "=" * 60)
    print(f"DONE — {len(df)} unique posts → reddit_data.csv")
    print(f"  Tier 1: {len(df[df['tier']==1])} posts")
    print(f"  Tier 2: {len(df[df['tier']==2])} posts")
    print(f"  Viral (score>5000):  {len(df[df['engagement_bucket']=='viral'])}")
    print(f"  High  (score>1000):  {len(df[df['engagement_bucket']=='high'])}")
    print(f"  Subreddits found: {df['subreddit'].nunique()}")
    print(f"  Date range: {df['created_date'].min()} → {df['created_date'].max()}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())