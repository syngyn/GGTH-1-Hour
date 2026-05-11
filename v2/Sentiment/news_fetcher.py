"""Async fetcher for free forex news sources (RSS + optional APIs)."""
import asyncio
import aiohttp
import feedparser
import hashlib
import json
import logging
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import List, Optional

log = logging.getLogger(__name__)


@dataclass
class NewsItem:
    id: str
    title: str
    summary: str
    url: str
    source: str
    published: datetime

    @classmethod
    def make(cls, title: str, summary: str, url: str,
             source: str, published: datetime) -> "NewsItem":
        h = hashlib.sha1(f"{url}|{title}".encode("utf-8")).hexdigest()[:16]
        return cls(id=h, title=title or "", summary=summary or "",
                   url=url or "", source=source, published=published)


# Free RSS feeds -- no API key required
RSS_FEEDS = [
    ("https://www.fxstreet.com/rss/news",                       "fxstreet"),
    ("https://www.forexlive.com/feed/news",                     "forexlive"),
    ("https://www.investing.com/rss/news_25.rss",               "investing"),
    ("https://www.investing.com/rss/news_1.rss",                "investing"),
    ("https://www.dailyfx.com/feeds/market-news",               "dailyfx"),
     ("https://feeds.marketwatch.com/marketwatch/topstories/",   "marketwatch"),
]


async def _fetch_text(session: aiohttp.ClientSession, url: str,
                      timeout: int = 15) -> Optional[str]:
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as r:
            if r.status == 200:
                return await r.text()
            log.debug("%s -> HTTP %d", url, r.status)
    except Exception as e:
        log.warning("fetch failed %s: %s", url, e)
    return None


async def _fetch_rss(session, url: str, source: str) -> List[NewsItem]:
    text = await _fetch_text(session, url)
    if not text:
        return []
    feed = feedparser.parse(text)
    items: List[NewsItem] = []
    for e in feed.entries[:50]:
        try:
            if getattr(e, "published_parsed", None):
                pub = datetime(*e.published_parsed[:6], tzinfo=timezone.utc)
            elif getattr(e, "updated_parsed", None):
                pub = datetime(*e.updated_parsed[:6], tzinfo=timezone.utc)
            else:
                pub = datetime.now(timezone.utc)
            items.append(NewsItem.make(
                title=getattr(e, "title", ""),
                summary=getattr(e, "summary", ""),
                url=getattr(e, "link", ""),
                source=source, published=pub,
            ))
        except Exception as ex:
            log.debug("rss entry skipped: %s", ex)
    return items


async def _fetch_newsapi(session, key: str) -> List[NewsItem]:
    if not key:
        return []
    url = ("https://newsapi.org/v2/everything?"
           "q=forex%20OR%20currency%20OR%20fed%20OR%20ecb%20OR%20boj%20OR%20boe&"
           "language=en&sortBy=publishedAt&pageSize=100&apiKey=" + key)
    txt = await _fetch_text(session, url)
    if not txt:
        return []
    try:
        data = json.loads(txt)
    except Exception:
        return []
    out = []
    for a in data.get("articles", []):
        try:
            pub = datetime.fromisoformat(a["publishedAt"].replace("Z", "+00:00"))
            out.append(NewsItem.make(
                title=a.get("title", ""),
                summary=a.get("description", "") or "",
                url=a.get("url", ""),
                source="newsapi", published=pub,
            ))
        except Exception:
            continue
    return out


async def _fetch_finnhub(session, key: str) -> List[NewsItem]:
    if not key:
        return []
    url = f"https://finnhub.io/api/v1/news?category=forex&token={key}"
    txt = await _fetch_text(session, url)
    if not txt:
        return []
    try:
        data = json.loads(txt)
    except Exception:
        return []
    out = []
    for a in data:
        try:
            pub = datetime.fromtimestamp(a.get("datetime", 0), tz=timezone.utc)
            out.append(NewsItem.make(
                title=a.get("headline", ""),
                summary=a.get("summary", "") or "",
                url=a.get("url", ""),
                source="finnhub", published=pub,
            ))
        except Exception:
            continue
    return out


async def fetch_all(newsapi_key: str = "",
                    finnhub_key: str = "") -> List[NewsItem]:
    timeout = aiohttp.ClientTimeout(total=30)
    headers = {"User-Agent": "ForexSentiment/1.0 (+research)"}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        tasks = [_fetch_rss(session, u, s) for u, s in RSS_FEEDS]
        tasks.append(_fetch_newsapi(session, newsapi_key))
        tasks.append(_fetch_finnhub(session, finnhub_key))
        results = await asyncio.gather(*tasks, return_exceptions=True)

    out: List[NewsItem] = []
    seen = set()
    for r in results:
        if isinstance(r, Exception):
            log.warning("source failed: %s", r)
            continue
        for it in r:
            if it.id in seen:
                continue
            seen.add(it.id)
            out.append(it)
    return out