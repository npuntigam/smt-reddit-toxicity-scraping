import praw
import pandas as pd
from datetime import datetime, timezone

# =========================
# 1) Reddit API setup
# =========================
reddit = praw.Reddit(
    client_id="YOUR_CLIENT_ID",
    client_secret="YOUR_CLIENT_SECRET",
    user_agent="toxicity-research-finance-probe by u/YOUR_USERNAME"
)

# =========================
# 2) Config
# =========================
SUBREDDIT = "finance"
POST_LIMIT = 30
MAX_COMMENTS_PER_POST = 50
SORT_MODE = "new"

# =========================
# 3) Helpers
# =========================
def utc_to_features(created_utc: float) -> dict:
    dt = datetime.fromtimestamp(created_utc, tz=timezone.utc)
    return {
        "created_datetime_utc": dt.isoformat(),
        "date_utc": dt.date().isoformat(),
        "weekday_utc": dt.strftime("%A"),
        "hour_utc": dt.hour,
        "is_weekend_utc": dt.weekday() >= 5
    }

def clean_text(text: str) -> str:
    if text is None:
        return ""
    return text.replace("\r", " ").replace("\n", " ").strip()

# =========================
# 4) Collect posts
# =========================
subreddit = reddit.subreddit(SUBREDDIT)

if SORT_MODE == "new":
    submissions = subreddit.new(limit=POST_LIMIT)
elif SORT_MODE == "hot":
    submissions = subreddit.hot(limit=POST_LIMIT)
elif SORT_MODE == "top":
    submissions = subreddit.top(limit=POST_LIMIT)
else:
    raise ValueError("Unsupported SORT_MODE")

posts_data = []
comments_data = []

for submission in submissions:
    post_time = utc_to_features(submission.created_utc)

    title = clean_text(submission.title)
    selftext = clean_text(submission.selftext)
    full_post_text = f"{title} {selftext}".strip()

    posts_data.append({
        "platform": "reddit",
        "content_type": "post",
        "subreddit": SUBREDDIT,
        "topic_fine": "finance",
        "topic_group": "professional",
        "post_id": submission.id,
        "parent_post_id": submission.id,
        "comment_id": None,
        "author": str(submission.author) if submission.author else None,
        "title": title,
        "selftext": selftext,
        "text": full_post_text,
        "score": submission.score,
        "upvote_ratio": getattr(submission, "upvote_ratio", None),
        "num_comments": submission.num_comments,
        "permalink": f"https://reddit.com{submission.permalink}",
        "is_self": submission.is_self,
        "over_18": submission.over_18,
        **post_time
    })

    # Load comments
    submission.comments.replace_more(limit=0)

    count = 0
    for comment in submission.comments.list():
        if count >= MAX_COMMENTS_PER_POST:
            break

        body = clean_text(comment.body)
        # exclude deleted / removed
        if not body or body in {"[deleted]", "[removed]"}:
            continue

        comment_time = utc_to_features(comment.created_utc)

        comments_data.append({
            "platform": "reddit",
            "content_type": "comment",
            "subreddit": SUBREDDIT,
            "topic_fine": "finance",
            "topic_group": "professional",
            "post_id": submission.id,
            "parent_post_id": submission.id,
            "comment_id": comment.id,
            "parent_comment_id": comment.parent_id,
            "author": str(comment.author) if comment.author else None,
            "title": None,
            "selftext": None,
            "text": body,
            "score": comment.score,
            "upvote_ratio": None,
            "num_comments": None,
            "permalink": f"https://reddit.com{comment.permalink}",
            "is_self": None,
            "over_18": submission.over_18,
            "comment_depth": getattr(comment, "depth", None),
            **comment_time
        })

        count += 1

# =========================
# 5) Save results
# =========================
posts_df = pd.DataFrame(posts_data)
comments_df = pd.DataFrame(comments_data)

combined_df = pd.concat([posts_df, comments_df], ignore_index=True)

posts_df.to_csv("reddit_finance_posts_probe.csv", index=False)
comments_df.to_csv("reddit_finance_comments_probe.csv", index=False)
combined_df.to_csv("reddit_finance_combined_probe.csv", index=False)

print("Done.")
print(f"Posts collected: {len(posts_df)}")
print(f"Comments collected: {len(comments_df)}")
print(combined_df.head(10))
