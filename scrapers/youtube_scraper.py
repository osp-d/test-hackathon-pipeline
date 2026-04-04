import requests
import pandas as pd
import time
from datetime import datetime

API_KEY = "AIzaSyA8PdfXGk15EIjN94wsFU-KYiBWjUT7Llk"  # console.cloud.google.com → Enable YouTube Data API v3
BASE_URL = "https://www.googleapis.com/youtube/v3"

QUERIES = ["Claude AI", "Claude Anthropic", "Claude vs ChatGPT", "Claude sonnet", "Anthropic Claude"]


def get_videos(query, max_results=50):
    """Search for videos matching query"""
    url = f"{BASE_URL}/search"
    params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "maxResults": 50,
        "order": "relevance",
        "relevanceLanguage": "en",
        "key": API_KEY,
    }

    videos = []
    next_page_token = None

    while len(videos) < max_results:
        if next_page_token:
            params["pageToken"] = next_page_token

        try:
            r = requests.get(url, params=params, timeout=10)
            if r.status_code == 403:
                print("  API quota exceeded — stop for today")
                return videos
            data = r.json()
        except Exception as e:
            print(f"  Error: {e}")
            break

        items = data.get("items", [])
        if not items:
            break

        for item in items:
            videos.append({
                "video_id": item["id"]["videoId"],
                "title": item["snippet"]["title"],
                "channel_name": item["snippet"]["channelTitle"],
                "channel_id": item["snippet"]["channelId"],
                "published_at": item["snippet"]["publishedAt"],
                "description": item["snippet"].get("description", "")[:400],
                "query_used": query,
            })

        next_page_token = data.get("nextPageToken")
        if not next_page_token:
            break
        time.sleep(0.5)

    return videos


def get_video_stats(video_ids):
    """Fetch statistics for up to 50 video IDs in one API call"""
    url = f"{BASE_URL}/videos"
    params = {
        "part": "statistics,contentDetails",
        "id": ",".join(video_ids),
        "key": API_KEY,
    }

    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        stats = {}
        for item in data.get("items", []):
            vid_id = item["id"]
            s = item.get("statistics", {})
            d = item.get("contentDetails", {})
            stats[vid_id] = {
                "view_count": int(s.get("viewCount", 0)),
                "like_count": int(s.get("likeCount", 0)),
                "comment_count": int(s.get("commentCount", 0)),
                "duration_iso": d.get("duration", ""),  # e.g. PT12M34S
            }
        return stats
    except Exception as e:
        print(f"  Stats error: {e}")
        return {}


def get_top_comments(video_id):
    """Fetch top 3 comments — mirrors Reddit comment collection"""
    url = f"{BASE_URL}/commentThreads"
    params = {
        "part": "snippet",
        "videoId": video_id,
        "order": "relevance",
        "maxResults": 3,
        "key": API_KEY,
    }

    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        comments = []
        for item in data.get("items", []):
            c = item["snippet"]["topLevelComment"]["snippet"]
            comments.append({
                "body": c.get("textDisplay", "")[:200],
                "score": c.get("likeCount", 0),
                "author": c.get("authorDisplayName", ""),
            })
        return comments
    except:
        return []  # comments disabled on many videos — handle gracefully


def parse_duration(iso_duration):
    """Convert PT12M34S → total seconds"""
    import re
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_duration)
    if not match:
        return None
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


def main():
    all_videos = []

    # Step 1 — collect video IDs and basic metadata
    for query in QUERIES:
        print(f"\nSearching: '{query}'...")
        videos = get_videos(query, max_results=50)
        print(f"  → {len(videos)} videos found")
        all_videos.extend(videos)
        time.sleep(1)

    # Deduplicate by video_id before fetching stats (save API quota)
    df = pd.DataFrame(all_videos)
    df.drop_duplicates(subset="video_id", inplace=True)
    print(f"\n{len(df)} unique videos — fetching stats...")

    # Step 2 — fetch stats in batches of 50 (1 API call per batch)
    video_ids = df["video_id"].tolist()
    all_stats = {}
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i+50]
        stats = get_video_stats(batch)
        all_stats.update(stats)
        print(f"  Stats fetched: {min(i+50, len(video_ids))}/{len(video_ids)}")
        time.sleep(0.5)

    # Step 3 — enrich each video row
    rows = []
    for _, row in df.iterrows():
        vid_id = row["video_id"]
        s = all_stats.get(vid_id, {})

        published = row["published_at"]  # "2024-03-24T14:22:00Z"
        dt = datetime.strptime(published, "%Y-%m-%dT%H:%M:%SZ")

        view_count = s.get("view_count", 0)
        like_count = s.get("like_count", 0)
        comment_count = s.get("comment_count", 0)
        duration_sec = parse_duration(s.get("duration_iso", ""))

        # Virality signals — mirrors Reddit's score_per_comment logic
        like_to_view_ratio = round(like_count / max(view_count, 1), 4)
        comment_to_view_ratio = round(comment_count / max(view_count, 1), 4)
        like_to_comment_ratio = round(like_count / max(comment_count, 1), 2)
        # High likes + low comments = passive boosted content (engineered)
        # High comments + lower likes = genuine debate (organic)

        video = {
            # --- Identity ---
            "platform": "youtube",
            "video_id": vid_id,
            "url": f"https://youtube.com/watch?v={vid_id}",
            "title": row["title"],
            "description": row["description"],
            "channel_name": row["channel_name"],
            "channel_id": row["channel_id"],
            "query_used": row["query_used"],

            # --- Timing (mirrors Reddit) ---
            "created_date": dt.strftime("%Y-%m-%d"),
            "created_utc": int(dt.timestamp()),
            "created_hour": dt.hour,
            "day_of_week": dt.strftime("%A"),

            # --- Engagement ---
            "view_count": view_count,
            "like_count": like_count,
            "comment_count": comment_count,
            "duration_seconds": duration_sec,

            # --- Derived virality signals ---
            "like_to_view_ratio": like_to_view_ratio,
            "comment_to_view_ratio": comment_to_view_ratio,
            "like_to_comment_ratio": like_to_comment_ratio,
            "engagement_bucket": (
                "viral" if view_count > 100000
                else "mid" if view_count > 10000
                else "low"
            ),
        }

        # --- Top comments (mirrors Reddit) ---
        print(f"  Fetching comments: {row['title'][:50]}")
        comments = get_top_comments(vid_id)
        video["top_comment_1"] = comments[0]["body"] if len(comments) > 0 else None
        video["top_comment_1_score"] = comments[0]["score"] if len(comments) > 0 else None
        video["top_comment_2"] = comments[1]["body"] if len(comments) > 1 else None
        video["top_comment_3"] = comments[2]["body"] if len(comments) > 2 else None
        time.sleep(0.5)

        rows.append(video)

    df_final = pd.DataFrame(rows)
    df_final.to_csv("youtube_data.csv", index=False)
    print(f"\nDone. {len(df_final)} videos → youtube_data.csv")


if __name__ == "__main__":
    main()