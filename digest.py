#!/usr/bin/env python3
"""
Daily personal content digest.

Fetches content across your permanent topics (config.json), this week's
temporary focus (weekly_focus.json), and topics the app has discovered
about you over time (discovered_topics.json) - scores everything against
the learned taste profile, adds a daily "get to know you" question and a
phrase-of-the-day language card, and writes both a dashboard and an email.

Run manually:  python digest.py
Run in CI:     see .github/workflows/daily-digest.yml
"""

import os
import json
import html
import random
import smtplib
import urllib.parse
from datetime import date, datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import content_sources as cs
import taste_profile as tp
import weekly_focus as wf
import discovered_topics as dt
import daily_discovery as dd
import pronunciation as pron

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(ROOT, "config.json")
SEEN_PATH = os.path.join(ROOT, "data", "seen_items.json")
PHRASE_BANK_PATH = os.path.join(ROOT, "data", "phrase_bank.json")
DASHBOARD_PATH = os.path.join(ROOT, "docs", "index.html")

TOPIC_COLORS = {
    "bts": "#C084FC", "nba": "#FB923C", "nfl": "#4ADE80", "smash": "#FACC15",
    "valorant": "#F87171", "world_news": "#60A5FA", "books": "#2DD4BF", "podcasts": "#F472B6",
}
TOPIC_EMOJI = {
    "bts": "\U0001F3A4", "nba": "\U0001F3C0", "nfl": "\U0001F3C8", "smash": "\U0001F3AE",
    "valorant": "\U0001F3AF", "world_news": "\U0001F4F0", "books": "\U0001F4DA", "podcasts": "\U0001F3A7",
}
DEFAULT_COLOR = "#FBBF24"
DEFAULT_EMOJI = "\u2728"
TYPE_LABELS = {"article": "Article", "youtube": "Video", "book": "Book", "podcast": "Podcast"}


def topic_color(topic_id):
    return TOPIC_COLORS.get(topic_id, DEFAULT_COLOR)


def topic_emoji(topic_id):
    return TOPIC_EMOJI.get(topic_id, DEFAULT_EMOJI)


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def load_phrase_bank():
    with open(PHRASE_BANK_PATH) as f:
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


def build_feedback_url(item, action, repo):
    label = "like" if action == "like" else "dislike"
    icon = "\U0001F44D" if action == "like" else "\U0001F44E"
    title = f"{icon} {label.title()}: {item['title'][:80]}"

    payload = json.dumps({
        "item_id": item["id"], "type": item["type"], "topic": item["topic"],
        "creator": item.get("creator", ""), "action": action,
    })
    body = (
        f"<!-- digest-feedback\n{payload}\n-->\n"
        f"**Item:** {item['title']}\n\n**Link:** {item['url']}\n\n"
        f"_Submitting this issue logs your feedback. It will be auto-closed._"
    )
    base = f"https://github.com/{repo}/issues/new"
    query = urllib.parse.urlencode({"title": title, "body": body, "labels": f"digest-feedback,{label}"})
    return f"{base}?{query}"


def _slugify(text):
    return "adhoc_" + "".join(c if c.isalnum() else "_" for c in text.lower()).strip("_")[:40]


def gather_candidates(config, focus=None, discovered=None):
    candidates = []

    for phrase in (focus or {}).get("ad_hoc_topics", []):
        topic_id = _slugify(phrase)
        for item in cs.fetch_google_news(phrase, topic_id, max_results=4):
            item["topic_label"] = phrase
            candidates.append((item, 6))
        for item in cs.fetch_youtube(phrase, topic_id, max_results=3):
            if not cs.is_clickbait(item["title"], config.get("clickbait_phrases", [])):
                item["topic_label"] = phrase
                candidates.append((item, 6))

    for topic_id, info in (discovered or {}).get("topics", {}).items():
        phrase = info["label"]
        weight = info["confidence"]
        for item in cs.fetch_google_news(phrase, topic_id, max_results=4):
            item["topic_label"] = phrase
            candidates.append((item, weight))
        for item in cs.fetch_youtube(phrase, topic_id, max_results=3):
            if not cs.is_clickbait(item["title"], config.get("clickbait_phrases", [])):
                item["topic_label"] = phrase
                candidates.append((item, weight))

    for topic in config["topics"]:
        weight = topic.get("static_weight", 1)
        short_form = topic.get("short_form_only", False)

        for q in topic.get("news_queries", []):
            for item in cs.fetch_google_news(q, topic["id"]):
                if short_form:
                    item["summary"] = item["title"]
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
        selected.extend(by_topic.get(topic["id"], [])[:per_topic])

    for topic_id, topic_items in by_topic.items():
        if topic_id.startswith("adhoc_") or topic_id.startswith("disc_"):
            selected.extend(topic_items[:2])

    books_n = config.get("books", {}).get("items_per_digest", 1)
    selected.extend(by_topic.get("books", [])[:books_n])

    pod_n = config.get("podcasts", {}).get("items_per_digest", 1)
    selected.extend(by_topic.get("podcasts", [])[:pod_n])

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


def render_card(item, score, is_new, repo):
    like_url = build_feedback_url(item, "like", repo)
    dislike_url = build_feedback_url(item, "dislike", repo)
    type_label = TYPE_LABELS.get(item["type"], item["type"].title())
    topic_display = item.get("topic_label", item["topic"].replace("_", " ").title())
    color = topic_color(item["topic"])
    stamp = "<span class='stamp'>NEW</span>" if is_new else ""

    image_url = item.get("image", "")
    if image_url:
        media_html = f"<div class='card-media'><img src='{html.escape(image_url)}' alt='' loading='lazy'></div>"
    else:
        emoji = topic_emoji(item["topic"])
        media_html = (
            f"<div class='card-media placeholder' "
            f"style='background: linear-gradient(135deg, {color}55, {color}22)'>"
            f"<span class='placeholder-emoji'>{emoji}</span></div>"
        )

    return f"""
    <div class="card" style="--accent: {color}">
      {media_html}
      <div class="card-body">
        <div class="card-topic-row">
          <span class="topic-chip" style="background:{color}33; color:{color}">{html.escape(topic_display)}</span>
          {stamp}
        </div>
        <a class="card-title" href="{html.escape(item['url'])}" target="_blank" rel="noopener">{html.escape(item['title'])}</a>
        <div class="card-meta">{html.escape(item.get('creator',''))} &middot; {html.escape(type_label)}</div>
        <div class="card-feedback">
          <a class="fb like" href="{html.escape(like_url)}" target="_blank" rel="noopener">&#128077;</a>
          <a class="fb dislike" href="{html.escape(dislike_url)}" target="_blank" rel="noopener">&#128078;</a>
        </div>
      </div>
    </div>"""


def render_phrase_section(phrase, translations, repo):
    cards = []
    for t in translations:
        ipa, audio_rel = pron.get_pronunciation(phrase, t["code"], t["translated"]) if t["translated"] else ("", "")
        ipa_html = f"<div class='phrase-ipa'>[{html.escape(ipa)}]</div>" if ipa else ""
        audio_html = (
            f"<audio controls preload='none' class='phrase-audio'>"
            f"<source src='{html.escape(audio_rel)}' type='audio/mpeg'></audio>"
            if audio_rel else ""
        )
        cards.append(f"""
      <div class="phrase-card">
        <div class="phrase-flag">{t['flag']}</div>
        <div class="phrase-lang">{html.escape(t['label'])}</div>
        <div class="phrase-text">{html.escape(t['translated']) if t['translated'] else '<em>unavailable today</em>'}</div>
        {ipa_html}
        {audio_html}
      </div>""")
    return f"""
    <section class="phrase-section">
      <h2 class="section-title">\U0001F30D Phrase of the Day</h2>
      <p class="phrase-english">"{html.escape(phrase)}"</p>
      <div class="phrase-grid">{''.join(cards)}</div>
    </section>"""


def render_discovery_section(question, reply_url):
    return f"""
    <section class="discovery-section">
      <h2 class="section-title">\U0001F9E9 Get to Know You</h2>
      <p class="discovery-question">{html.escape(question)}</p>
      <a class="discovery-btn" href="{html.escape(reply_url)}" target="_blank" rel="noopener">Answer this &rarr;</a>
    </section>"""


def generate_dashboard(selected, new_ids, config, repo, generated_at, phrase, translations, question, discovery_url, discovered_count):
    cards_html = "".join(
        render_card(item, score, item["id"] in new_ids, repo) for item, score in selected
    ) or "<p class='empty'>No items yet - check back after the next run.</p>"

    new_count = sum(1 for item, _ in selected if item["id"] in new_ids)
    phrase_section = render_phrase_section(phrase, translations, repo)
    discovery_section = render_discovery_section(question, discovery_url)

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Daily Mix - Personal Digest</title>
<style>
  :root {{
    --bg: #171923; --bg-panel: #1F2233; --ink: #F5F3FF; --ink-dim: #A3A8C3;
    --line: #33374F; --purple: #C084FC; --pink: #F472B6; --amber: #FBBF24;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin:0; background: radial-gradient(circle at top left, #241F3D, var(--bg) 55%);
    color:var(--ink); font-family:'IBM Plex Sans',-apple-system,Segoe UI,sans-serif;
  }}
  .mono {{ font-family:'IBM Plex Mono',monospace; }}
  header {{
    padding:40px 32px 28px;
    background: linear-gradient(120deg, #7C3AED33, #EC489933, #F59E0B22);
    border-bottom: 1px solid var(--line);
  }}
  .eyebrow {{ font-family:'IBM Plex Mono',monospace; letter-spacing:.12em; text-transform:uppercase; color:var(--amber); font-size:12px; margin-bottom:6px; }}
  h1 {{ font-family:'Space Grotesk','IBM Plex Sans',sans-serif; font-size:36px; margin:0 0 6px; background: linear-gradient(90deg, var(--purple), var(--pink)); -webkit-background-clip: text; background-clip: text; color: transparent; }}
  .meta {{ color:var(--ink-dim); font-size:14px; font-family:'IBM Plex Mono',monospace; }}
  .summary-bar {{ display:flex; gap:18px; padding:22px 32px; flex-wrap:wrap; }}
  .summary-card {{ background:var(--bg-panel); border:1px solid var(--line); border-radius:10px; padding:14px 20px; min-width:130px; }}
  .summary-card .num {{ font-family:'Space Grotesk',sans-serif; font-size:26px; color:var(--amber); }}
  .summary-card .lbl {{ font-size:11px; color:var(--ink-dim); text-transform:uppercase; letter-spacing:.08em; }}

  section {{ margin: 8px 32px 32px; }}
  .section-title {{ font-family:'Space Grotesk',sans-serif; font-size:18px; margin-bottom:14px; }}

  .phrase-section {{ background: linear-gradient(120deg,#312244,#1F2233); border:1px solid var(--line); border-radius:14px; padding:22px 24px; }}
  .phrase-english {{ font-size:20px; font-weight:600; margin: 0 0 16px; }}
  .phrase-grid {{ display:grid; grid-template-columns: repeat(auto-fill, minmax(160px,1fr)); gap:14px; }}
  .phrase-card {{ background:var(--bg-panel); border:1px solid var(--line); border-radius:10px; padding:14px; text-align:center; }}
  .phrase-flag {{ font-size:26px; }}
  .phrase-lang {{ font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:var(--ink-dim); margin:6px 0 4px; }}
  .phrase-text {{ font-size:15px; font-weight:600; }}
  .phrase-ipa {{ font-family:'IBM Plex Mono',monospace; font-size:12px; color:var(--ink-dim); margin-top:4px; }}
  .phrase-audio {{ width:100%; height:32px; margin-top:10px; }}

  .discovery-section {{ background: linear-gradient(120deg,#3D2A17,#1F2233); border:1px solid var(--line); border-radius:14px; padding:22px 24px; }}
  .discovery-question {{ font-size:17px; margin: 0 0 16px; }}
  .discovery-btn {{ display:inline-block; background: var(--amber); color:#1F1300; font-weight:700; padding:10px 18px; border-radius:8px; text-decoration:none; }}

  .card-grid {{ display:grid; grid-template-columns: repeat(auto-fill, minmax(260px,1fr)); gap:20px; padding: 0 32px 48px; }}
  .card {{ background:var(--bg-panel); border:1px solid var(--line); border-top: 4px solid var(--accent); border-radius:12px; overflow:hidden; display:flex; flex-direction:column; }}
  .card-media {{ width:100%; height:150px; overflow:hidden; }}
  .card-media img {{ width:100%; height:100%; object-fit:cover; display:block; }}
  .card-media.placeholder {{ display:flex; align-items:center; justify-content:center; }}
  .placeholder-emoji {{ font-size:48px; }}
  .card-body {{ padding:16px; display:flex; flex-direction:column; gap:8px; flex:1; }}
  .card-topic-row {{ display:flex; align-items:center; gap:8px; }}
  .topic-chip {{ font-size:11px; font-weight:700; padding:3px 10px; border-radius:20px; text-transform:uppercase; letter-spacing:.04em; }}
  .stamp {{ font-family:'IBM Plex Mono',monospace; font-size:10px; color:var(--amber); border:1px solid var(--amber); padding:1px 6px; border-radius:3px; }}
  .card-title {{ color:var(--ink); font-weight:700; text-decoration:none; font-size:15px; line-height:1.35; }}
  .card-title:hover {{ color: var(--pink); }}
  .card-meta {{ font-size:12px; color:var(--ink-dim); }}
  .card-feedback {{ margin-top:auto; padding-top:6px; }}
  .fb {{ display:inline-block; text-decoration:none; font-size:20px; padding:4px 10px 4px 0; }}

  .empty {{ padding: 0 32px; color: var(--ink-dim); }}
  footer {{ padding:24px 32px 40px; color:var(--ink-dim); font-size:12px; font-family:'IBM Plex Mono',monospace; }}
  footer a {{ color: var(--pink); }}
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
  <div class="summary-card"><div class="num">{len(config.get('topics', []))}</div><div class="lbl">Core topics</div></div>
  <div class="summary-card"><div class="num">{discovered_count}</div><div class="lbl">Discovered topics</div></div>
</div>

{phrase_section}
{discovery_section}

<section>
  <h2 class="section-title">\U0001F4F1 Today's Mix</h2>
  <div class="card-grid">{cards_html}</div>
</section>

<footer>
  Sources: Google News, YouTube, Google Books, iTunes, MyMemory &middot; Rebuilt daily by GitHub Actions &middot;
  Tap &#128077;/&#128078; to teach it your taste &middot; Edit <span class="mono">config.json</span> to retune topics &middot;
  <a href="checkin.html">Weekly check-in &amp; profile summary</a>
</footer>
</body>
</html>
"""
    os.makedirs(os.path.dirname(DASHBOARD_PATH), exist_ok=True)
    with open(DASHBOARD_PATH, "w") as f:
        f.write(page)


def send_email(selected, new_ids, dashboard_url, repo, phrase, translations, question, discovery_url):
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")
    to_email = os.environ.get("TO_EMAIL")
    if not (smtp_user and smtp_pass and to_email):
        print("SMTP secrets not set - skipping email, dashboard was still updated.")
        return

    new_items = [item for item, _ in selected if item["id"] in new_ids]
    if not new_items:
        print("No new items - skipping email.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Your Daily Mix - {len(new_items)} new picks"
    msg["From"] = smtp_user
    msg["To"] = to_email

    html_items, text_lines = [], []
    for item in new_items:
        like_url = build_feedback_url(item, "like", repo)
        dislike_url = build_feedback_url(item, "dislike", repo)
        type_label = TYPE_LABELS.get(item["type"], item["type"].title())
        topic_display = item.get("topic_label", item["topic"])
        color = topic_color(item["topic"])
        img_tag = f"<img src='{html.escape(item['image'])}' width='90' style='border-radius:8px;float:left;margin-right:12px'>" if item.get("image") else ""

        text_lines.append(f"- [{topic_display}] {item['title']} ({type_label}) - {item['url']}")
        html_items.append(
            f"<li style='margin-bottom:18px; overflow:hidden; border-left:4px solid {color}; padding-left:10px'>"
            f"{img_tag}"
            f"<b>{html.escape(item['title'])}</b> "
            f"<span style='color:#888'>[{html.escape(type_label)} &middot; {html.escape(topic_display)}]</span><br>"
            f"<a href='{html.escape(item['url'])}'>{html.escape(item['url'])}</a><br>"
            f"<a href='{html.escape(like_url)}'>\U0001F44D Like</a> &nbsp; "
            f"<a href='{html.escape(dislike_url)}'>\U0001F44E Dislike</a>"
            f"</li>"
        )

    phrase_html = ""
    for t in translations:
        ipa, audio_rel = pron.get_pronunciation(phrase, t["code"], t["translated"]) if t["translated"] else ("", "")
        ipa_span = f" <span style='color:#aaa;font-family:monospace'>[{html.escape(ipa)}]</span>" if ipa else ""
        audio_link = ""
        if audio_rel and dashboard_url:
            audio_url = dashboard_url.rstrip("/") + "/" + audio_rel
            audio_link = f" <a href='{html.escape(audio_url)}'>\U0001F50A play</a>"
        phrase_html += (
            f"<div style='margin:4px 0'>{t['flag']} <b>{html.escape(t['translated']) if t['translated'] else '-'}</b>"
            f" <span style='color:#888'>({html.escape(t['label'])})</span>{ipa_span}{audio_link}</div>"
        )

    text_body = "\n".join(text_lines) + f"\n\nPhrase of the day: \"{phrase}\"\n"
    text_body += "\n".join(f"{t['label']}: {t['translated']}" for t in translations)
    text_body += f"\n\nGet to know you: {question}\nAnswer: {discovery_url}\n\nFull dashboard: {dashboard_url}"

    html_body = (
        f"<ul style='list-style:none;padding:0'>{''.join(html_items)}</ul>"
        f"<h3>\U0001F30D Phrase of the Day: \"{html.escape(phrase)}\"</h3>"
        f"<p>{phrase_html}</p>"
        f"<h3>\U0001F9E9 {html.escape(question)}</h3>"
        f"<p><a href='{html.escape(discovery_url)}'>Answer this &rarr;</a></p>"
        f"<p><a href='{html.escape(dashboard_url)}'>View full dashboard</a></p>"
    )

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, [to_email], msg.as_string())
    print(f"Email sent to {to_email} ({len(new_items)} new items).")


def main():
    config = load_config()
    repo = os.environ.get("GITHUB_REPOSITORY", "YOUR-USERNAME/YOUR-REPO")

    profile = tp.load_taste_profile()
    profile = tp.apply_decay(profile)

    focus = wf.load_weekly_focus()

    discovered = dt.load_discovered_topics()
    discovered = dt.decay_and_prune(discovered)

    candidates = gather_candidates(config, focus, discovered)
    print(f"Fetched {len(candidates)} raw candidates.")

    selected = select_digest(candidates, config, profile, focus)
    print(f"Selected {len(selected)} items for today's digest.")

    seen = load_seen()
    new_ids = {item["id"] for item, _ in selected if item["id"] not in seen}
    for item, _ in selected:
        seen[item["id"]] = seen.get(item["id"], datetime.now(timezone.utc).isoformat())
    save_seen(seen)

    tp.save_taste_profile(profile)
    dt.save_discovered_topics(discovered)

    phrase_bank = load_phrase_bank()
    phrase = phrase_bank[date.today().timetuple().tm_yday % len(phrase_bank)]
    translations = cs.fetch_translations(phrase, config.get("languages", []))

    question = dd.todays_question()
    discovery_url = dd.build_discovery_reply_url(question, repo)

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    dashboard_url = config.get("dashboard_url", "")

    generate_dashboard(
        selected, new_ids, config, repo, generated_at,
        phrase, translations, question, discovery_url, len(discovered.get("topics", {})),
    )

    send_email(selected, new_ids, dashboard_url, repo, phrase, translations, question, discovery_url)


if __name__ == "__main__":
    main()
