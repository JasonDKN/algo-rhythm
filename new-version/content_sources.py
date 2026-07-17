"""
Content source fetchers. Each function returns a list of normalized item dicts:
{id, type, title, url, source, topic, creator, summary, published}
"""

import os
import re
import html
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

REQUEST_TIMEOUT = 20
UA = {"User-Agent": "Mozilla/5.0 (compatible; content-digest-bot/1.0)"}


def _clean(text):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# Google News RSS — no API key required
# ---------------------------------------------------------------------------

def fetch_google_news(query, topic_id, max_results=8):
    url = "https://news.google.com/rss/search"
    params = {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"}
    try:
        r = requests.get(url, params=params, headers=UA, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as e:
        print(f"[google_news] '{query}' failed: {e}")
        return []

    items = []
    for item in root.findall(".//item")[:max_results]:
        title = _clean(item.findtext("title", ""))
        link = item.findtext("link", "")
        pub_date = item.findtext("pubDate", "")
        source_el = item.find("source")
        source_name = source_el.text if source_el is not None else "Google News"
        # Article-level unique id from the link
        item_id = "news-" + re.sub(r"\W+", "", link)[-40:]
        items.append({
            "id": item_id,
            "type": "article",
            "title": title,
            "url": link,
            "source": source_name,
            "topic": topic_id,
            "creator": source_name,
            "summary": "",
            "published": pub_date,
        })
    return items


# ---------------------------------------------------------------------------
# YouTube Data API v3 — requires YOUTUBE_API_KEY
# ---------------------------------------------------------------------------

def fetch_youtube(query, topic_id, max_results=6):
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        return []

    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "order": "date",
        "maxResults": max_results,
        "key": api_key,
    }
    try:
        r = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[youtube] '{query}' failed: {e}")
        return []

    items = []
    for entry in data.get("items", []):
        vid = entry.get("id", {}).get("videoId")
        if not vid:
            continue
        snippet = entry.get("snippet", {})
        thumbnails = snippet.get("thumbnails", {})
        thumb_url = (thumbnails.get("high") or thumbnails.get("medium") or thumbnails.get("default") or {}).get("url", "")
        items.append({
            "id": f"yt-{vid}",
            "type": "youtube",
            "title": _clean(snippet.get("title", "")),
            "url": f"https://www.youtube.com/watch?v={vid}",
            "source": "YouTube",
            "topic": topic_id,
            "creator": snippet.get("channelTitle", ""),
            "summary": _clean(snippet.get("description", ""))[:200],
            "published": snippet.get("publishedAt", ""),
            "image": thumb_url,
        })
    return items


def is_clickbait(title, clickbait_phrases):
    t = title.lower()
    if any(p in t for p in clickbait_phrases):
        return True
    # heuristic: excessive caps / exclamation points
    letters = [c for c in title if c.isalpha()]
    if letters:
        caps_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
        if caps_ratio > 0.6 and len(letters) > 8:
            return True
    if title.count("!") >= 3:
        return True
    return False


# ---------------------------------------------------------------------------
# Google Books API — no key required for basic search
# ---------------------------------------------------------------------------

def fetch_books(genre, max_results=4):
    url = "https://www.googleapis.com/books/v1/volumes"
    params = {"q": f"subject:{genre}", "orderBy": "newest", "maxResults": max_results}
    try:
        r = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[books] '{genre}' failed: {e}")
        return []

    items = []
    for entry in data.get("items", []):
        vol = entry.get("volumeInfo", {})
        title = vol.get("title", "")
        authors = ", ".join(vol.get("authors", []) or ["Unknown author"])
        link = vol.get("infoLink", "")
        book_id = entry.get("id", "")
        cover = (vol.get("imageLinks", {}) or {}).get("thumbnail", "").replace("http://", "https://")
        items.append({
            "id": f"book-{book_id}",
            "type": "book",
            "title": title,
            "url": link,
            "source": "Google Books",
            "topic": "books",
            "creator": authors,
            "summary": _clean(vol.get("description", ""))[:220],
            "published": vol.get("publishedDate", ""),
            "image": cover,
        })
    return items


# ---------------------------------------------------------------------------
# iTunes Search API for podcasts — no key required, with a real duration check
# ---------------------------------------------------------------------------

def _parse_itunes_duration(duration_str):
    """<itunes:duration> can be 'HH:MM:SS', 'MM:SS', or plain seconds."""
    if not duration_str:
        return None
    duration_str = duration_str.strip()
    if duration_str.isdigit():
        return int(duration_str) // 60
    parts = duration_str.split(":")
    try:
        parts = [int(p) for p in parts]
    except ValueError:
        return None
    if len(parts) == 3:
        h, m, s = parts
        return h * 60 + m + (1 if s else 0)
    if len(parts) == 2:
        m, s = parts
        return m + (1 if s else 0)
    return None


def _latest_episode_minutes(feed_url):
    """Fetch a podcast's RSS feed and return the latest episode's duration in minutes."""
    try:
        r = requests.get(feed_url, headers=UA, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception:
        return None

    ns = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}
    item = root.find(".//item")
    if item is None:
        return None
    dur_el = item.find("itunes:duration", ns)
    if dur_el is None or not dur_el.text:
        return None
    return _parse_itunes_duration(dur_el.text)


def fetch_podcasts(search_term, max_duration_minutes, max_results=3):
    url = "https://itunes.apple.com/search"
    params = {"term": search_term, "media": "podcast", "limit": max_results}
    try:
        r = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[podcasts] '{search_term}' failed: {e}")
        return []

    items = []
    for entry in data.get("results", []):
        feed_url = entry.get("feedUrl")
        title = entry.get("collectionName", "")
        artist = entry.get("artistName", "")
        track_view_url = entry.get("collectionViewUrl", "")

        minutes = _latest_episode_minutes(feed_url) if feed_url else None
        if minutes is not None and minutes > max_duration_minutes:
            continue  # respects the "no 3-hour podcasts" rule

        items.append({
            "id": f"podcast-{entry.get('collectionId')}",
            "type": "podcast",
            "title": title,
            "url": track_view_url,
            "source": "iTunes",
            "topic": "podcasts",
            "creator": artist,
            "summary": f"Latest episode ~{minutes} min" if minutes else "Duration unknown",
            "published": "",
        })
    return items


# ---------------------------------------------------------------------------
# MyMemory Translation API — free, no key required (5000 chars/day anonymous,
# 50000/day if an email is attached via the `de` param). Quality is
# crowdsourced/machine-translated and can be inconsistent for idiomatic phrases.
# ---------------------------------------------------------------------------

def fetch_translations(phrase, languages):
    """languages: list of {'code','label','flag'} dicts."""
    email = os.environ.get("TO_EMAIL", "")
    results = []
    for lang in languages:
        url = "https://api.mymemory.translated.net/get"
        params = {"q": phrase, "langpair": f"en|{lang['code']}"}
        if email:
            params["de"] = email
        try:
            r = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            data = r.json()
            translated = data.get("responseData", {}).get("translatedText", "")
        except Exception as e:
            print(f"[translate] {lang['code']} failed: {e}")
            translated = ""
        results.append({
            "code": lang["code"],
            "label": lang["label"],
            "flag": lang.get("flag", ""),
            "translated": html.unescape(translated) if translated else "",
        })
    return results
