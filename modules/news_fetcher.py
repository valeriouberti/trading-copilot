"""RSS news aggregator module.

Fetches and filters financial news from configured RSS feeds,
deduplicates by title similarity, and returns structured results.
"""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

import feedparser
from dateutil import parser as date_parser

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.85
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2.0


def fetch_news(
    feeds: list[dict[str, str]],
    lookback_hours: int = 16,
    assets: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Fetch and deduplicate news articles from RSS feeds.

    Args:
        feeds: List of dicts with 'url' and 'name' keys.
        lookback_hours: Only include articles from the last N hours.
        assets: Optional list of asset dicts for prioritization.

    Returns:
        Deduplicated list of article dicts with keys:
        title, summary, source, published_at.
    """
    cutoff = datetime.now(timezone.utc).timestamp() - (lookback_hours * 3600)
    all_articles: list[dict[str, Any]] = []

    for feed_cfg in feeds:
        url = feed_cfg["url"]
        source_name = feed_cfg.get("name", url)
        articles = _fetch_single_feed(url, source_name, cutoff)
        all_articles.extend(articles)
        logger.info("Feed '%s': %d articles after time filter", source_name, len(articles))

    all_articles.sort(key=lambda a: a["published_at"], reverse=True)
    deduplicated = _deduplicate(all_articles)
    logger.info(
        "Total articles: %d raw -> %d after dedup",
        len(all_articles),
        len(deduplicated),
    )

    if assets:
        deduplicated = _prioritize_by_assets(deduplicated, assets)

    return deduplicated


def fetch_news_for_asset(
    feeds: list[dict[str, str]],
    lookback_hours: int = 16,
    asset: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Fetch news specifically relevant to a single asset.

    1. Fetches from all configured generic RSS feeds
    2. Adds an asset-specific Yahoo Finance RSS feed
    3. Filters to keep only articles mentioning the asset
    4. Falls back to prioritized generic news if filter yields < 3 articles
    """
    if asset is None:
        return fetch_news(feeds, lookback_hours)

    symbol = asset.get("symbol", "")

    # Add asset-specific Yahoo Finance RSS feed
    asset_feeds = list(feeds)
    clean_symbol = symbol.replace("=", "%3D")
    asset_feeds.append({
        "url": f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={clean_symbol}&region=US&lang=en-US",
        "name": f"Yahoo Finance {symbol}",
    })

    all_articles = fetch_news(asset_feeds, lookback_hours, assets=[asset])

    # Build filter terms from symbol and display_name
    terms = _build_asset_search_terms(asset)

    # Filter to asset-relevant articles
    relevant = [a for a in all_articles if _article_mentions_asset(a, terms)]

    # If too few results, fall back to the full prioritized list
    if len(relevant) < 3:
        return all_articles

    return relevant


def _build_asset_search_terms(asset: dict[str, str]) -> list[str]:
    """Build search terms for matching articles to an asset."""
    terms: list[str] = []
    symbol = asset.get("symbol", "").upper()
    display_name = asset.get("display_name", "")

    # Raw symbol without suffixes (=F, =X)
    base_symbol = symbol.split("=")[0]
    terms.append(base_symbol.lower())

    # Display name words (skip very short/common ones)
    skip_words = {"inc", "inc.", "the", "corp", "corp.", "ltd", "ltd."}
    if display_name:
        for word in display_name.split():
            w = word.lower().strip(".,()[]")
            if len(w) > 2 and w not in skip_words:
                terms.append(w)

    return list(dict.fromkeys(terms))


def _article_mentions_asset(article: dict[str, Any], terms: list[str]) -> bool:
    """Check if an article mentions any of the asset search terms."""
    text = f"{article.get('title', '')} {article.get('summary', '')}".lower()
    return any(term in text for term in terms)


def _fetch_single_feed(
    url: str,
    source_name: str,
    cutoff_timestamp: float,
) -> list[dict[str, Any]]:
    """Fetch a single RSS feed with retry logic."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            feed = feedparser.parse(url)
            if feed.bozo and not feed.entries:
                raise ValueError(f"Feed parse error: {feed.bozo_exception}")
            break
        except Exception as exc:
            if attempt == MAX_RETRIES:
                logger.error(
                    "Failed to fetch feed '%s' after %d attempts: %s",
                    source_name,
                    MAX_RETRIES,
                    exc,
                )
                return []
            wait = RETRY_BACKOFF_BASE ** attempt
            logger.warning(
                "Retry %d/%d for feed '%s' in %.1fs: %s",
                attempt,
                MAX_RETRIES,
                source_name,
                wait,
                exc,
            )
            time.sleep(wait)

    articles: list[dict[str, Any]] = []
    for entry in feed.entries:
        published_at = _parse_entry_date(entry)
        if published_at is None or published_at.timestamp() < cutoff_timestamp:
            continue

        title = entry.get("title", "").strip()
        summary = entry.get("summary", entry.get("description", "")).strip()
        # Strip HTML tags from summary
        if "<" in summary:
            import re
            summary = re.sub(r"<[^>]+>", "", summary).strip()

        if not title:
            continue

        articles.append({
            "title": title,
            "summary": summary[:500] if summary else "",
            "source": source_name,
            "published_at": published_at,
        })

    return articles


def _parse_entry_date(entry: Any) -> datetime | None:
    """Extract and parse the publication date from a feed entry."""
    for field in ("published", "updated", "created"):
        raw = entry.get(field)
        if raw:
            try:
                dt = date_parser.parse(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except (ValueError, OverflowError):
                continue

    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        try:
            return datetime(*parsed[:6], tzinfo=timezone.utc)
        except (TypeError, ValueError):
            pass

    return None


def _title_hash(title: str) -> str:
    """Compute a normalized hash for fast exact-match dedup."""
    normalized = " ".join(title.lower().split())
    return hashlib.md5(normalized.encode()).hexdigest()


def _jaccard_similarity(a: str, b: str) -> float:
    """Word-level Jaccard similarity — catches word reordering."""
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


JACCARD_THRESHOLD = 0.70


def _deduplicate(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove articles with similar titles.

    Uses a three-phase approach:
    1. Hash pre-filter for exact/near-exact duplicates (O(1) lookup)
    2. SequenceMatcher for character-level fuzzy duplicates
    3. Jaccard similarity for word-level duplicates (catches reordering)
    """
    unique: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    seen_titles: list[str] = []

    for article in articles:
        title = article["title"].lower()
        h = _title_hash(title)

        # Phase 1: exact hash match
        if h in seen_hashes:
            continue
        seen_hashes.add(h)

        # Phase 2+3: fuzzy match against already-seen titles
        is_duplicate = False
        for seen in seen_titles:
            if SequenceMatcher(None, title, seen).ratio() >= SIMILARITY_THRESHOLD:
                is_duplicate = True
                break
            if _jaccard_similarity(title, seen) >= JACCARD_THRESHOLD:
                is_duplicate = True
                break

        if not is_duplicate:
            unique.append(article)
            seen_titles.append(title)

    return unique


def _prioritize_by_assets(
    articles: list[dict[str, Any]],
    assets: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Prioritize articles that mention configured assets."""
    asset_terms: list[str] = []
    for a in assets:
        asset_terms.append(a.get("symbol", "").lower())
        name = a.get("display_name", "").lower()
        if name:
            asset_terms.extend(name.split())
    # Remove empty and very short terms
    asset_terms = [t for t in asset_terms if len(t) > 2]

    def mentions_asset(article: dict[str, Any]) -> bool:
        text = f"{article['title']} {article.get('summary', '')}".lower()
        return any(term in text for term in asset_terms)

    prioritized = [a for a in articles if mentions_asset(a)]
    rest = [a for a in articles if not mentions_asset(a)]
    return prioritized + rest


def summarize_news_with_llm(
    articles: list[dict[str, Any]],
    asset: dict[str, str] | None = None,
    max_bullets: int = 5,
) -> list[str]:
    """Distill articles into key bullet-point summaries using the LLM.

    Returns up to ``max_bullets`` concise bullet points. Falls back to
    simple title extraction if the LLM is unavailable.
    """
    import os

    if not articles:
        return []

    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        # Fallback: just return top titles
        return [a["title"] for a in articles[:max_bullets]]

    from modules.groq_client import get_groq_client

    client = get_groq_client(api_key)
    if client is None:
        return [a["title"] for a in articles[:max_bullets]]

    asset_name = (
        f" for {asset.get('display_name', asset.get('symbol', ''))}"
        if asset else ""
    )
    articles_block = "\n".join(
        f"- [{a.get('source', '?')}] {a['title']}"
        for a in articles[:15]
    )

    prompt = f"""Summarize these financial news articles{asset_name} into exactly {max_bullets} concise bullet points.
Each bullet should be 1 sentence max, focusing on market impact.

ARTICLES:
{articles_block}

Respond ONLY with {max_bullets} bullet points (one per line, starting with "- ").
No preamble, no numbering, no markdown."""

    try:
        groq_model = os.environ.get("GROQ_MODEL", "qwen/qwen3-32b")
        response = client.chat.completions.create(
            model=groq_model,
            messages=[
                {"role": "system", "content": "You are a financial news summarizer. Be concise and focus on market impact."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=300,
        )
        raw = response.choices[0].message.content.strip()
        bullets = [
            line.lstrip("- ").strip()
            for line in raw.split("\n")
            if line.strip().startswith("-") or line.strip().startswith("•")
        ]
        return bullets[:max_bullets] if bullets else [a["title"] for a in articles[:max_bullets]]
    except Exception as exc:
        logger.warning("News summarization failed, using title fallback: %s", exc)
        return [a["title"] for a in articles[:max_bullets]]


if __name__ == "__main__":
    import yaml

    logging.basicConfig(level=logging.INFO)
    with open("config.yaml") as f:
        config = yaml.safe_load(f)
    news = fetch_news(config["rss_feeds"], config["lookback_hours"])
    for item in news[:10]:
        print(f"[{item['source']}] {item['title']}")
        print(f"  {item['published_at']}")
        print()
