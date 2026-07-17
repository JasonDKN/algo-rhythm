#!/usr/bin/env python3
"""
Daily personal content digest.

Fetches BTS/NBA/NFL/Smash/Valorant/world-news/books/podcasts, scores each
item against config.json (static profile) + taste_profile.json (learned from
your Like/Dislike feedback), writes a dashboard to docs/index.html, and
emails a digest with feedback links for each item.

Run manually:  python digest.py
Run in CI:     see .github/workflows/daily-digest.yml
"""

import os
import json
import html
import random
import smtplib
import urllib.parse
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import content_sources as cs
import taste_profile as tp
import weekly_focus as wf

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(ROOT, "config.json")
SEEN_PATH = os.path.join(ROOT, "data", "seen_items.json")
DASHBOARD_PATH = os.path.join(ROOT, "docs", "index.html")


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def load_seen():
    if not os.path.exists(SEEN_PATH):
        return {}
    try:
        with open(SEEN_PATH) as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}


def save_seen(seen):
    os.makedirs(os.path.dirname(SEEN_PATH), exist_ok=True)
    with open(SEEN_PATH, "w") as f:
        json.dump(seen, f, indent=2)


# ---------------------------------------------------------------------------
# Feedback links — GitHub Issues, since there's no server to hit
# ---------------------------------------------------------------------------

def build_feedback_url(item, action, repo):
    label = "like" if action == "like" else "dislike"
    icon = "\U0001F44D" if action == "like" else "\U0001F44E"
    title = f"{icon} {label.title()}: {item['title'][:80]}"

    payload = json.dumps({
        "item_id": item["id"],
        "type": item["type"],
        "topic": item["topic"],
        "creator": item.get("creator", ""),
        "action": action,
    })
    body = (
        f"<!-- digest-feedback\n{payload}\n-->\n"
        f"**Item:** {item['title']}\n\n"
        f"**Link:** {item['url']}\n\n"
        f"_Submitting this issue logs your feedback. It will be auto-closed._"
    )

    base = f"https://github.com/{repo}/issues/new"
    query = urllib.parse.urlencode({
        "title": title,
        "body": body,
        "labels": f"digest-feedback,{label}",
    })
    return f"{base}?{query}"


# ---------------------------------------------------------------------------
# Fetch + score everything
# ---------------------------------------------------------------------------

def _slugify(text):
    return "adhoc_" + "".join(c if c.isalnum() else "_" for c in text.lower()).strip("_")[:40]


def gather_candidates(config, focus=None):
    """Returns a flat list of items tagged with which topic/static weight they belong to."""
    candidates = []  # list of (item, static_weight)

    for phrase in (focus or {}).get("ad_hoc_topics", []):
        topic_id = _slugify(phrase)
        for item in cs.fetch_google_news(phrase, topic_id, max_results=4):
            item["topic_label"] = phrase
            candidates.append((item, 6))  # explicitly requested this week -> high priority
        for item in cs.fetch_youtube(phrase, topic_id, max_results=3):
            if not cs.is_clickbait(item["title"], config.get("clickbait_phrases", [])):
                item["topic_label"] = phrase
                candidates.append((item, 6))

    for topic in config["topics"]:
        weight = topic.get("static_weight", 1)
        short_form = topic.get("short_form_only", False)

        for q in topic.get("news_queries", []):
            for item in cs.fetch_google_news(q, topic["id"]):
                if short_form:
                    item["summary"] = item["title"]  # headline-only, no deep dive
                if any(bad.lower() in item["title"].lower() for bad in config.get("exclude_keywords", [])):
                    continue
                candidates.append((item, weight))

        for q in topic.get("youtube_queries", []):
            for item in cs.fetch_youtube(q, topic["id"]):
                if cs.is_clickbait(item["title"], config.get("clickbait_phrases", [])):
                    continue
                candidates.append((item, weight))

    books_cfg = config.get("books", {})
    if books_cfg.get("enabled"):
        for genre in books_cfg.get("genres", []):
            for item in cs.fetch_books(genre):
                candidates.append((item, 2))

    pod_cfg = config.get("podcasts", {})
    if pod_cfg.get("enabled"):
        for term in pod_cfg.get("search_terms", []):
            for item in cs.fetch_podcasts(term, pod_cfg.get("max_duration_minutes", 180)):
                candidates.append((item, 2))

    return candidates


def select_digest(candidates, config, profile, focus=None):
    """Score everything, dedupe, then pick top N per topic (+ one wildcard)."""
    weekly_boosts = (focus or {}).get("topic_boosts", {})

    scored = []
    seen_ids = set()
    for item, static_weight in candidates:
        if item["id"] in seen_ids:
            continue
        seen_ids.add(item["id"])
        score = tp.score_item(item, static_weight, profile) + weekly_boosts.get(item["topic"], 0)
        scored.append((item, score))

    scored.sort(key=lambda x: x[1], reverse=True)

    by_topic = {}
    for item, score in scored:
        by_topic.setdefault(item["topic"], []).append((item, score))

    selected = []
    per_topic = config.get("items_per_topic", 2)

    for topic in config["topics"]:
        topic_items = by_topic.get(topic["id"], [])
        selected.extend(topic_items[:per_topic])

    # This week's ad-hoc topics (from a freeform check-in reply) get their own slots
    for topic_id, topic_items in by_topic.items():
        if topic_id.startswith("adhoc_"):
            selected.extend(topic_items[:2])

    books_n = config.get("books", {}).get("items_per_digest", 1)
    selected.extend(by_topic.get("books", [])[:books_n])

    pod_n = config.get("podcasts", {}).get("items_per_digest", 1)
    selected.extend(by_topic.get("podcasts", [])[:pod_n])

    # Wildcard: a decent-scoring item from a topic NOT already represented,
    # so the profile doesn't collapse into an echo chamber.
    if config.get("wildcard_enabled", True):
        chosen_topics = {item["topic"] for item, _ in selected}
        leftovers = [
            (item, score) for item, score in scored
            if item["topic"] not in chosen_topics and item["id"] not in {i["id"] for i, _ in selected}
        ]
        if leftovers:
            wildcard = random.choice(leftovers[: max(1, len(leftovers) // 2)])
            selected.append(wildcard)

    return selected


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

TYPE_LABELS = {"article": "Article", "youtube": "Video", "book": "Book", "podcast": "Podcast"}


def generate_dashboard(selected, new_ids, config, repo, generated_at):
    rows = []
    for idx, (item, score) in enumerate(selected, start=1):
        is_new = item["id"] in new_ids
        stub = f"{idx:04d}"
        stamp = "<span class='stamp'>NEW</span>" if is_new else ""
        like_url = build_feedback_url(item, "like", repo)
        dislike_url = build_feedback_url(item, "dislike", repo)
        type_label = TYPE_LABELS.get(item["type"], item["type"].title())

        rows.append(f"""
        <tr class="{'is-new' if is_new else ''}">
          <td class="stub">#{stub}</td>
          <td class="title-cell">
            <a href="{html.escape(item['url'])}" target="_blank" rel="noopener">{html.escape(item['title'])}</a>
            {stamp}
            <div class="meta-line">{html.escape(item.get('creator',''))} &middot; <span class="chip">{html.escape(type_label)}</span></div>
          </td>
          <td>{html.escape(item.get('topic_label', item['topic'].replace('_',' ').title()))}</td>
          <td class="feedback">
            <a class="fb like" href="{html.escape(like_url)}" target="_blank" rel="noopener">&#128077;</a>
            <a class="fb dislike" href="{html.escape(dislike_url)}" target="_blank" rel="noopener">&#128078;</a>
          </td>
        </tr>""")

    new_count = sum(1 for item, _ in selected if item["id"] in new_ids)

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Daily Mix — Personal Digest</title>
<style>
  :root {{
    --bg: #1B2430; --bg-panel: #212C3B; --ink: #EDEFF2; --ink-dim: #9AA6B5;
    --amber: #E8A33D; --teal: #4C8C8B; --line: #34435A; --new-bg: #2A3446;
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink); font-family:'IBM Plex Sans',-apple-system,Segoe UI,sans-serif; }}
  .mono {{ font-family:'IBM Plex Mono','Courier New',monospace; }}
  header {{ padding:36px 32px 24px; border-bottom:2px dashed var(--line); }}
  .eyebrow {{ font-family:'IBM Plex Mono',monospace; letter-spacing:.12em; text-transform:uppercase; color:var(--amber); font-size:12px; margin-bottom:6px; }}
  h1 {{ font-family:'Space Grotesk','IBM Plex Sans',sans-serif; font-size:32px; margin:0 0 6px; letter-spacing:-.01em; }}
  .meta {{ color:var(--ink-dim); font-size:14px; font-family:'IBM Plex Mono',monospace; }}
  .summary-bar {{ display:flex; gap:24px; padding:20px 32px; flex-wrap:wrap; }}
  .summary-card {{ background:var(--bg-panel); border:1px solid var(--line); border-radius:4px; padding:14px 20px; min-width:140px; }}
  .summary-card .num {{ font-family:'Space Grotesk',sans-serif; font-size:26px; color:var(--amber); }}
  .summary-card .lbl {{ font-size:12px; color:var(--ink-dim); text-transform:uppercase; letter-spacing:.08em; }}
  main {{ padding:0 32px 48px; }}
  table {{ width:100%; border-collapse:collapse; margin-top:12px; }}
  thead th {{ text-align:left; font-family:'IBM Plex Mono',monospace; text-transform:uppercase; font-size:11px; letter-spacing:.08em; color:var(--ink-dim); padding:10px 12px; border-bottom:2px solid var(--line); }}
  tbody td {{ padding:14px 12px; border-bottom:1px solid var(--line); vertical-align:top; font-size:14px; }}
  tbody tr.is-new {{ background:var(--new-bg); }}
  .stub {{ font-family:'IBM Plex Mono',monospace; color:var(--ink-dim); font-size:12px; }}
  .title-cell a {{ color:var(--ink); font-weight:600; text-decoration:none; }}
  .title-cell a:hover {{ color:var(--amber); text-decoration:underline; }}
  .meta-line {{ margin-top:4px; font-size:12px; color:var(--ink-dim); }}
  .stamp {{ display:inline-block; margin-left:8px; padding:1px 8px; border:1.5px solid var(--amber); color:var(--amber); font-family:'IBM Plex Mono',monospace; font-size:10px; letter-spacing:.08em; border-radius:3px; transform:rotate(-3deg); }}
  .chip {{ font-family:'IBM Plex Mono',monospace; font-size:10px; color:var(--teal); border:1px solid var(--teal); border-radius:3px; padding:1px 6px; }}
  .feedback {{ white-space:nowrap; }}
  .fb {{ display:inline-block; text-decoration:none; font-size:18px; padding:4px 8px; border-radius:4px; }}
  .fb.like:hover {{ background: rgba(232,163,61,0.15); }}
  .fb.dislike:hover {{ background: rgba(76,140,139,0.15); }}
  footer {{ padding:24px 32px 40px; color:var(--ink-dim); font-size:12px; font-family:'IBM Plex Mono',monospace; }}
  @media (max-width:720px) {{
    thead {{ display:none; }}
    tbody tr {{ display:block; margin-bottom:16px; border:1px solid var(--line); border-radius:4px; }}
    tbody td {{ display:block; border-bottom:none; padding:6px 14px; }}
  }}
</style>
</head>
<body>
<header>
  <div class="eyebrow">Personal Feed &middot; Updated Daily</div>
  <h1>Daily Mix</h1>
  <div class="meta">Generated {html.escape(generated_at)} &middot; {html.escape(config.get('recipient_name',''))}</div>
</header>

<div class="summary-bar">
  <div class="summary-card"><div class="num">{len(selected)}</div><div class="lbl">Items today</div></div>
  <div class="summary-card"><div class="num">{new_count}</div><div class="lbl">New today</div></div>
  <div class="summary-card"><div class="num">{len(config.get('topics', []))}</div><div class="lbl">Topics tracked</div></div>
</div>

<main>
<table>
  <thead><tr><th>#</th><th>Item</th><th>Topic</th><th>Feedback</th></tr></thead>
  <tbody>
    {''.join(rows) if rows else '<tr><td colspan="4">No items yet — check back after the next run.</td></tr>'}
  </tbody>
</table>
</main>

<footer>
  Sources: Google News, YouTube, Google Books, iTunes &middot; Rebuilt daily by GitHub Actions &middot;
  Tap &#128077;/&#128078; to teach it your taste &middot; Edit <span class="mono">config.json</span> to retune topics &middot;
  <a href="checkin.html" style="color:var(--teal)">Weekly check-in &amp; profile summary</a>
</footer>
</body>
</html>
"""
    os.makedirs(os.path.dirname(DASHBOARD_PATH), exist_ok=True)
    with open(DASHBOARD_PATH, "w") as f:
        f.write(page)


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def send_email(selected, new_ids, dashboard_url, repo):
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")
    to_email = os.environ.get("TO_EMAIL")
    if not (smtp_user and smtp_pass and to_email):
        print("SMTP secrets not set — skipping email, dashboard was still updated.")
        return

    new_items = [item for item, _ in selected if item["id"] in new_ids]
    if not new_items:
        print("No new items — skipping email.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Your Daily Mix — {len(new_items)} new picks"
    msg["From"] = smtp_user
    msg["To"] = to_email

    html_items, text_lines = [], []
    for item in new_items:
        like_url = build_feedback_url(item, "like", repo)
        dislike_url = build_feedback_url(item, "dislike", repo)
        type_label = TYPE_LABELS.get(item["type"], item["type"].title())
        topic_display = item.get("topic_label", item["topic"])
        text_lines.append(f"- [{topic_display}] {item['title']} ({type_label}) — {item['url']}")
        html_items.append(
            f"<li style='margin-bottom:14px'>"
            f"<b>{html.escape(item['title'])}</b> "
            f"<span style='color:#888'>[{html.escape(type_label)} &middot; {html.escape(topic_display)}]</span><br>"
            f"<a href='{html.escape(item['url'])}'>{html.escape(item['url'])}</a><br>"
            f"<a href='{html.escape(like_url)}'>\U0001F44D Like</a> &nbsp; "
            f"<a href='{html.escape(dislike_url)}'>\U0001F44E Dislike</a>"
            f"</li>"
        )

    text_body = "\n".join(text_lines) + f"\n\nFull dashboard: {dashboard_url}"
    html_body = f"<ul>{''.join(html_items)}</ul><p><a href='{html.escape(dashboard_url)}'>View full dashboard</a></p>"

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, [to_email], msg.as_string())
    print(f"Email sent to {to_email} ({len(new_items)} new items).")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    config = load_config()
    repo = os.environ.get("GITHUB_REPOSITORY", "YOUR-USERNAME/YOUR-REPO")

    profile = tp.load_taste_profile()
    profile = tp.apply_decay(profile)

    focus = wf.load_weekly_focus()

    candidates = gather_candidates(config, focus)
    print(f"Fetched {len(candidates)} raw candidates.")

    selected = select_digest(candidates, config, profile, focus)
    print(f"Selected {len(selected)} items for today's digest.")

    seen = load_seen()
    new_ids = {item["id"] for item, _ in selected if item["id"] not in seen}
    for item, _ in selected:
        seen[item["id"]] = seen.get(item["id"], datetime.now(timezone.utc).isoformat())
    save_seen(seen)

    tp.save_taste_profile(profile)  # persist the decay step even if no feedback arrived

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    generate_dashboard(selected, new_ids, config, repo, generated_at)

    send_email(selected, new_ids, config.get("dashboard_url", ""), repo)


if __name__ == "__main__":
    main()
