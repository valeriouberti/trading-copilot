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


# ---------------------------------------------------------------------------
# Per-ETF keyword mapping for news relevance scoring
# ---------------------------------------------------------------------------
# Each ETF maps to:
#   - extra_feeds: category-specific RSS feeds to fetch alongside generic ones
#   - keywords: terms that indicate an article is relevant to this ETF
#   - yahoo_proxies: US-listed equivalents for Yahoo Finance RSS (UCITS .MI
#     tickers have sparse Yahoo coverage; the US equivalents get more news)

_ETF_NEWS_CONFIG: dict[str, dict[str, Any]] = {
    "SWDA.MI": {
        "extra_feeds": [
            {"url": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=VT,ACWI&region=US&lang=en-US",
             "name": "Yahoo Global Equity ETFs"},
        ],
        "yahoo_proxies": ["VT", "ACWI"],
        "keywords": [
            "msci world", "global equit", "world index", "global stock",
            "global market", "world market", "developed market",
            "s&p 500", "sp500", "nasdaq", "stoxx", "ftse",
            "fed", "interest rate", "rate cut", "rate hike",
            "inflation", "gdp", "recession", "economy",
            "bull market", "bear market", "correction",
            "etf", "index fund", "passive invest",
        ],
    },
    "CSSPX.MI": {
        "extra_feeds": [
            {"url": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=SPY,VOO,IVV&region=US&lang=en-US",
             "name": "Yahoo S&P 500 ETFs"},
        ],
        "yahoo_proxies": ["SPY", "VOO", "IVV"],
        "keywords": [
            "s&p 500", "sp500", "s&p500", "sp 500",
            "wall street", "us stock", "us equit", "us market",
            "dow jones", "dow", "nyse",
            "fed", "fomc", "powell", "rate cut", "rate hike",
            "earnings", "big tech", "magnificent seven",
            "nvidia", "apple", "microsoft", "amazon", "google", "meta", "tesla",
        ],
    },
    "EQQQ.MI": {
        "extra_feeds": [
            {"url": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=QQQ,TQQQ&region=US&lang=en-US",
             "name": "Yahoo NASDAQ ETFs"},
        ],
        "yahoo_proxies": ["QQQ"],
        "keywords": [
            "nasdaq", "nasdaq-100", "nasdaq 100", "tech stock",
            "technology", "semiconductor", "chip", "ai stock",
            "artificial intelligence", "big tech", "growth stock",
            "nvidia", "apple", "microsoft", "amazon", "google",
            "meta", "tesla", "broadcom", "asml",
            "silicon valley", "tech sector", "software",
        ],
    },
    "MEUD.MI": {
        "extra_feeds": [
            {"url": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=VGK,EZU,FEZ&region=US&lang=en-US",
             "name": "Yahoo Europe ETFs"},
            {"url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=19794221",
             "name": "CNBC Europe"},
        ],
        "yahoo_proxies": ["VGK", "EZU"],
        "keywords": [
            "europe", "european", "eurozone", "euro zone",
            "stoxx", "euro stoxx", "dax", "cac", "ftse",
            "ecb", "lagarde", "european central bank",
            "eu economy", "german", "france", "italy",
            "uk market", "brexit", "european stock",
        ],
    },
    "IEEM.MI": {
        "extra_feeds": [
            {"url": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=EEM,VWO&region=US&lang=en-US",
             "name": "Yahoo EM ETFs"},
        ],
        "yahoo_proxies": ["EEM", "VWO"],
        "keywords": [
            "emerging market", "em stock", "developing countr",
            "china", "chinese", "india", "indian", "brazil",
            "south korea", "taiwan", "indonesia", "mexico",
            "brics", "hang seng", "shanghai",
            "tariff", "trade war", "sanctions",
            "commodity", "yuan", "rupee",
        ],
    },
    "SGLD.MI": {
        "extra_feeds": [
            {"url": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=GLD,IAU,SGOL&region=US&lang=en-US",
             "name": "Yahoo Gold ETFs"},
        ],
        "yahoo_proxies": ["GLD", "IAU"],
        "keywords": [
            "gold", "gold price", "precious metal", "bullion",
            "safe haven", "safe-haven", "haven asset",
            "central bank gold", "gold reserve",
            "geopolit", "war", "conflict", "tension",
            "inflation hedge", "real rate", "dollar weak",
            "mining", "gold miner",
        ],
    },
    "SEGA.MI": {
        "extra_feeds": [
            {"url": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=AGG,TLT,BND&region=US&lang=en-US",
             "name": "Yahoo Bond ETFs"},
        ],
        "yahoo_proxies": ["AGG", "TLT"],
        "keywords": [
            "bond", "treasury", "yield", "bund", "gilt",
            "sovereign debt", "government bond", "govt bond",
            "ecb rate", "interest rate", "rate cut", "rate hike",
            "inflation", "cpi", "deflation",
            "fixed income", "credit spread",
            "btp", "oat", "euro bond",
        ],
    },
    "AGGH.MI": {
        "extra_feeds": [
            {"url": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=AGG,BND,BNDX&region=US&lang=en-US",
             "name": "Yahoo Global Bond ETFs"},
        ],
        "yahoo_proxies": ["AGG", "BND", "BNDX"],
        "keywords": [
            "bond", "treasury", "yield", "fixed income",
            "global bond", "aggregate bond", "investment grade",
            "credit", "spread", "corporate bond",
            "fed rate", "ecb rate", "boj", "interest rate",
            "inflation", "cpi", "monetary policy",
            "quantitative tightening", "quantitative easing",
        ],
    },
}


def fetch_news_for_asset(
    feeds: list[dict[str, str]],
    lookback_hours: int = 16,
    asset: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Fetch news specifically relevant to a single asset.

    1. Fetches from all configured generic RSS feeds
    2. Adds per-ETF targeted feeds (Benzinga ETFs, Yahoo proxies, CNBC sectors)
    3. Scores articles by relevance to the ETF category
    4. Falls back to all articles if fewer than 3 match
    """
    if asset is None:
        return fetch_news(feeds, lookback_hours)

    symbol = asset.get("symbol", "")
    etf_config = _ETF_NEWS_CONFIG.get(symbol, {})

    # Build feed list: generic + ETF-specific extra feeds
    asset_feeds = list(feeds)

    # Add per-ETF targeted feeds
    for extra in etf_config.get("extra_feeds", []):
        asset_feeds.append(extra)

    # Add direct Yahoo Finance feed for the .MI symbol (sparse but occasionally useful)
    clean_symbol = symbol.replace("=", "%3D")
    asset_feeds.append({
        "url": f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={clean_symbol}&region=US&lang=en-US",
        "name": f"Yahoo Finance {symbol}",
    })

    all_articles = fetch_news(asset_feeds, lookback_hours, assets=[asset])

    # Score and filter articles by ETF relevance
    terms = _build_asset_search_terms(asset)
    scored = _score_articles_for_asset(all_articles, terms)

    # Keep articles that score above threshold
    relevant = [a for score, a in scored if score > 0]

    # Sort by relevance score (descending), then by recency
    relevant.sort(key=lambda a: a.get("_relevance", 0), reverse=True)

    # If too few results, fall back to the full list (generic macro news still useful)
    if len(relevant) < 3:
        return all_articles

    return relevant


def _build_asset_search_terms(asset: dict[str, str]) -> dict[str, list[str]]:
    """Build categorized search terms for matching articles to an asset.

    Returns a dict with:
      - "exact": high-confidence terms (symbol, ETF name) -> score 3
      - "category": category keywords from _ETF_NEWS_CONFIG -> score 2
      - "broad": broad market terms from display name -> score 1
    """
    symbol = asset.get("symbol", "").upper()
    display_name = asset.get("display_name", "")
    etf_config = _ETF_NEWS_CONFIG.get(symbol, {})

    exact: list[str] = []
    category: list[str] = []
    broad: list[str] = []

    # Exact: symbol (without .MI suffix), yahoo proxy symbols
    base = symbol.split(".")[0].lower()
    exact.append(base)
    for proxy in etf_config.get("yahoo_proxies", []):
        exact.append(proxy.lower())

    # Category: per-ETF keywords from config
    category.extend(etf_config.get("keywords", []))

    # Broad: display name words (skip filler)
    skip_words = {"inc", "inc.", "the", "corp", "corp.", "ltd", "ltd.",
                  "core", "ishares", "invesco", "amundi", "physical"}
    if display_name:
        for word in display_name.split():
            w = word.lower().strip(".,()[]")
            if len(w) > 2 and w not in skip_words:
                broad.append(w)

    return {"exact": exact, "category": category, "broad": broad}


def _score_articles_for_asset(
    articles: list[dict[str, Any]],
    terms: dict[str, list[str]],
) -> list[tuple[int, dict[str, Any]]]:
    """Score each article by relevance to an ETF.

    Scoring:
      - exact match (symbol, proxy ETF): +3
      - category keyword match: +2
      - broad term match: +1
    """
    scored: list[tuple[int, dict[str, Any]]] = []

    for article in articles:
        text = f"{article.get('title', '')} {article.get('summary', '')}".lower()
        score = 0

        for term in terms.get("exact", []):
            if term in text:
                score += 3
                break

        for term in terms.get("category", []):
            if term in text:
                score += 2
                break

        for term in terms.get("broad", []):
            if term in text:
                score += 1
                break

        article["_relevance"] = score
        scored.append((score, article))

    return scored


def _article_mentions_asset(article: dict[str, Any], terms: dict[str, list[str]] | list[str]) -> bool:
    """Check if an article mentions any of the asset search terms.

    Accepts both the new dict format and legacy list format.
    """
    text = f"{article.get('title', '')} {article.get('summary', '')}".lower()
    if isinstance(terms, dict):
        all_terms = terms.get("exact", []) + terms.get("category", []) + terms.get("broad", [])
    else:
        all_terms = terms
    return any(term in text for term in all_terms)


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
            "link": entry.get("link", ""),
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
    """Prioritize articles that mention configured assets using ETF keyword config."""
    # Build a combined set of all category keywords for the given assets
    all_terms: list[str] = []
    for a in assets:
        symbol = a.get("symbol", "")
        config = _ETF_NEWS_CONFIG.get(symbol, {})
        all_terms.extend(config.get("keywords", []))
        # Also add proxy symbols
        for proxy in config.get("yahoo_proxies", []):
            all_terms.append(proxy.lower())
        # And the base symbol
        base = symbol.split(".")[0].lower()
        if len(base) > 2:
            all_terms.append(base)
    # Deduplicate
    all_terms = list(dict.fromkeys(all_terms))

    def mentions_asset(article: dict[str, Any]) -> bool:
        text = f"{article['title']} {article.get('summary', '')}".lower()
        return any(term in text for term in all_terms)

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

    from modules.llm_client import get_active_provider
    if get_active_provider() == "none":
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
        from modules.llm_client import llm_call
        raw = llm_call(
            system_msg="You are a financial news summarizer. Be concise and focus on market impact.",
            user_msg=prompt,
            temperature=0.2,
            max_tokens=300,
        )
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
