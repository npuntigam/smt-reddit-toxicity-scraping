import logging
from datetime import datetime, timezone
import pandas as pd
import praw
from prawcore.exceptions import PrawcoreException
from dotenv import load_dotenv
import os

# =========================
# 1) Setups
# =========================
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT")

if not all([REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT]):
    raise ValueError("Missing Reddit API credentials in .env file")

reddit = praw.Reddit(
    client_id=REDDIT_CLIENT_ID,
    client_secret=REDDIT_CLIENT_SECRET,
    user_agent=REDDIT_USER_AGENT
)
reddit.read_only = True

# =========================
# 2) Config
# =========================
SUBREDDIT = "finance"
POST_LIMIT = 30
MAX_COMMENTS_PER_POST = 50
SORT_MODE = "new"

POSTS_OUTPUT = "reddit_finance_posts_probe.csv"
COMMENTS_OUTPUT = "reddit_finance_comments_probe.csv"
COMBINED_OUTPUT = "reddit_finance_combined_probe.csv"

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
# 4) Start info
# =========================
logger.info("Starting Reddit probe script")
logger.info("Configuration:")
logger.info("  SUBREDDIT=%s", SUBREDDIT)
logger.info("  POST_LIMIT=%s", POST_LIMIT)
logger.info("  MAX_COMMENTS_PER_POST=%s", MAX_COMMENTS_PER_POST)
logger.info("  SORT_MODE=%s", SORT_MODE)
logger.info("  READ_ONLY=%s", reddit.read_only)

# =========================
# 5) Collect posts
# =========================
posts_data = []
comments_data = []

posts_seen = 0
comments_seen = 0
comments_saved = 0
comments_skipped_deleted_removed = 0
posts_with_comment_errors = 0

try:
    logger.info("Connecting to subreddit r/%s", SUBREDDIT)
    subreddit = reddit.subreddit(SUBREDDIT)

    logger.info("Validating API access with subreddit display name fetch")
    logger.info("Connected successfully to r/%s", subreddit.display_name)

    if SORT_MODE == "new":
        submissions = subreddit.new(limit=POST_LIMIT)
    elif SORT_MODE == "hot":
        submissions = subreddit.hot(limit=POST_LIMIT)
    elif SORT_MODE == "top":
        submissions = subreddit.top(limit=POST_LIMIT)
    else:
        raise ValueError(f"Unsupported SORT_MODE: {SORT_MODE}")

    logger.info("Starting submission collection")

    for idx, submission in enumerate(submissions, start=1):
        posts_seen += 1

        logger.info(
            "Processing post %s/%s | id=%s | title=%s",
            idx,
            POST_LIMIT,
            submission.id,
            clean_text(submission.title)[:80]
        )

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
            "parent_comment_id": None,
            "author": str(submission.author) if submission.author else None,
            "title": title,
            "selftext": selftext,
            "text": full_post_text,
            "text_length": len(full_post_text),
            "score": submission.score,
            "upvote_ratio": getattr(submission, "upvote_ratio", None),
            "num_comments": submission.num_comments,
            "permalink": f"https://reddit.com{submission.permalink}",
            "is_self": submission.is_self,
            "over_18": submission.over_18,
            **post_time
        })

        try:
            logger.info("Loading comments for post id=%s", submission.id)
            submission.comments.replace_more(limit=0)
            flat_comments = submission.comments.list()

            logger.info(
                "Loaded %s flattened comments for post id=%s",
                len(flat_comments),
                submission.id
            )

            count = 0
            for comment in flat_comments:
                if count >= MAX_COMMENTS_PER_POST:
                    logger.info(
                        "Reached MAX_COMMENTS_PER_POST=%s for post id=%s",
                        MAX_COMMENTS_PER_POST,
                        submission.id
                    )
                    break

                comments_seen += 1
                body = clean_text(comment.body)

                if not body or body in {"[deleted]", "[removed]"}:
                    comments_skipped_deleted_removed += 1
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
                    "text_length": len(body),
                    "score": comment.score,
                    "upvote_ratio": None,
                    "num_comments": None,
                    "permalink": f"https://reddit.com{comment.permalink}",
                    "is_self": None,
                    "over_18": submission.over_18,
                    "comment_depth": getattr(comment, "depth", None),
                    **comment_time
                })

                comments_saved += 1
                count += 1

            logger.info("Saved %s comments for post id=%s", count, submission.id)

        except Exception as comment_error:
            posts_with_comment_errors += 1
            logger.exception(
                "Error while processing comments for post id=%s: %s",
                submission.id,
                comment_error
            )

except PrawcoreException as api_error:
    logger.exception("Reddit API / connection error: %s", api_error)
    raise
except Exception as e:
    logger.exception("Unexpected error during scraping: %s", e)
    raise

# =========================
# 6) Save results
# =========================
logger.info("Creating DataFrames")
posts_df = pd.DataFrame(posts_data)
comments_df = pd.DataFrame(comments_data)

combined_df = pd.concat([posts_df, comments_df], ignore_index=True)

logger.info("Saving CSV files")
posts_df.to_csv(POSTS_OUTPUT, index=False)
comments_df.to_csv(COMMENTS_OUTPUT, index=False)
combined_df.to_csv(COMBINED_OUTPUT, index=False)

# =========================
# 7) Final summary
# =========================
logger.info("Finished successfully")
logger.info("Posts collected: %s", len(posts_df))
logger.info("Comments collected: %s", len(comments_df))
logger.info("Posts seen total: %s", posts_seen)
logger.info("Comments seen total: %s", comments_seen)
logger.info("Comments saved total: %s", comments_saved)
logger.info(
    "Comments skipped ([deleted]/[removed]/empty): %s",
    comments_skipped_deleted_removed
)
logger.info("Posts with comment errors: %s", posts_with_comment_errors)
logger.info("Output files:")
logger.info("  %s", POSTS_OUTPUT)
logger.info("  %s", COMMENTS_OUTPUT)
logger.info("  %s", COMBINED_OUTPUT)

print("\n=== FINAL SUMMARY ===")
print(f"Posts collected: {len(posts_df)}")
print(f"Comments collected: {len(comments_df)}")
print(f"Posts seen total: {posts_seen}")
print(f"Comments seen total: {comments_seen}")
print(f"Comments saved total: {comments_saved}")
print(f"Comments skipped ([deleted]/[removed]/empty): {comments_skipped_deleted_removed}")
print(f"Posts with comment errors: {posts_with_comment_errors}")
print("\nCombined preview:")
print(combined_df.head(10))