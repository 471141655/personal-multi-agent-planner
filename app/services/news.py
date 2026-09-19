from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import urlsplit, urlunsplit
from xml.etree import ElementTree

import feedparser
import httpx

from app.schemas import NewsItem


SOURCES = {
    "OpenAI": "https://openai.com/news/rss.xml",
    "Google AI": "https://blog.google/technology/ai/rss/",
    "Hugging Face": "https://huggingface.co/blog/feed.xml",
}

SITEMAPS = {
    "Anthropic": ("https://www.anthropic.com/sitemap.xml", "/news/"),
    "DeepSeek": ("https://api-docs.deepseek.com/sitemap.xml", "/news/"),
}


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        result = parsedate_to_datetime(value)
        return result if result.tzinfo else result.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return result if result.tzinfo else result.replace(tzinfo=timezone.utc)
        except ValueError:
            return None


def _canonical_url(value: str) -> str:
    parts = urlsplit(value)
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def fetch_ai_news(days: int = 7, limit: int = 5) -> tuple[list[NewsItem], list[str]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    items: list[NewsItem] = []
    errors: list[str] = []
    seen: set[str] = set()

    with httpx.Client(timeout=8.0, follow_redirects=True, headers={"User-Agent": "PersonalLearningPlanner/0.1"}) as client:
        for source, url in SOURCES.items():
            try:
                response = client.get(url)
                response.raise_for_status()
                feed = feedparser.parse(response.content)
                if getattr(feed, "bozo", False) and not feed.entries:
                    raise ValueError("invalid feed")
                for entry in feed.entries[:12]:
                    link = str(entry.get("link", "")).strip()
                    title = str(entry.get("title", "")).strip()
                    if not link or not title:
                        continue
                    published = _parse_date(entry.get("published") or entry.get("updated"))
                    if published and published < cutoff:
                        continue
                    key = _canonical_url(link) or title.casefold()
                    if key in seen:
                        continue
                    seen.add(key)
                    items.append(
                        NewsItem(
                            title=title,
                            source=source,
                            published_at=published,
                            url=link,
                            excerpt=str(entry.get("summary", ""))[:1200],
                        )
                    )
            except Exception as exc:  # one source must not break the others
                errors.append(f"{source}: {type(exc).__name__}")

        for source, (url, path_marker) in SITEMAPS.items():
            try:
                response = client.get(url)
                response.raise_for_status()
                root = ElementTree.fromstring(response.content)
                namespace = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
                candidates: list[tuple[datetime | None, str]] = []
                for node in root.findall(f"{namespace}url"):
                    location_node = node.find(f"{namespace}loc")
                    modified_node = node.find(f"{namespace}lastmod")
                    link = (location_node.text or "").strip() if location_node is not None else ""
                    if not link or path_marker not in urlsplit(link).path:
                        continue
                    published = _parse_date((modified_node.text or "").strip() if modified_node is not None else None)
                    if published and published < cutoff:
                        continue
                    candidates.append((published, link))
                candidates.sort(key=lambda pair: pair[0] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
                for published, link in candidates[:8]:
                    key = _canonical_url(link)
                    if key in seen:
                        continue
                    seen.add(key)
                    slug = urlsplit(link).path.rstrip("/").split("/")[-1]
                    title = unescape(slug.replace("-", " ").replace("_", " ")).strip().title()
                    items.append(NewsItem(title=title or f"{source} 最新动态", source=source, published_at=published, url=link))
            except Exception as exc:
                errors.append(f"{source}: {type(exc).__name__}")

    items.sort(key=lambda item: item.published_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return items[:limit], errors
