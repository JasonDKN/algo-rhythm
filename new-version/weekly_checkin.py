#!/usr/bin/env python3
"""
Runs weekly (see .github/workflows/weekly-checkin.yml). Looks at what
actually happened this week (data/taste_profile.json's feedback_log),
writes a casual check-in message using varied templated phrasing (no LLM),
and asks 1-2 quick questions plus one open-ended one via pre-filled GitHub
Issue links — the same mechanism the daily Like/Dislike buttons use.
"""

import os
import json
import random
import smtplib
import urllib.parse
from collections import Counter
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import taste_profile as tp
import weekly_focus as wf

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(ROOT, "config.json")
CHECKIN_DASHBOARD_PATH = os.path.join(ROOT, "docs", "checkin.html")

OPENERS = [
    "Hey! Quick check-in on how this week's mix felt.",
    "Hi again — been a week, so let's do a gut-check on what's been landing.",
    "Hey, it's your weekly nudge — here's what I noticed this week.",
    "Checking in! Here's what stood out from this week's picks.",
]

TOP_TOPIC_LINES = [
    "You were clearly into {topic} this week — {likes} likes and barely any scrolling past it.",
    "{topic} was the standout — {likes} likes, easily the week's favorite.",
    "Looks like {topic} is having a moment for you: {likes} likes this week.",
]

COOL_TOPIC_LINES = [
    "{topic} didn't really land — {dislikes} dislikes, so I've eased off it.",
    "You skipped past most of the {topic} stuff — dialing that back.",
    "{topic} seems to be cooling off; I've turned it down a notch.",
]

NO_DATA_LINE = (
    "No likes or dislikes logged yet this week — totally fine, the tap-to-react "
    "links are right there on the dashboard whenever something catches your eye."
)

CLOSERS = [
    "Anything new on your radar this week?",
    "What's actually got your attention right now?",
    "Anything you want more (or less) of this coming week?",
]

CALLBACK_LINES = [
    "Last week you mentioned {topic} — hope the extra picks on that hit the mark.",
    "Following up on {topic} from last week's note — let me know if I should keep leaning into it.",
]


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def build_issue_url(title, body, labels, repo):
    base = f"https://github.com/{repo}/issues/new"
    query = urllib.parse.urlencode({"title": title, "body": body, "labels": ",".join(labels)})
    return f"{base}?{query}"


def build_quick_checkin_url(topic_id, topic_label, action, repo):
    """action: 'boost' or 'reduce'"""
    title = f"\U0001F4AC Weekly check-in: {action} {topic_label}"
    payload = json.dumps({"kind": "quick", "topic": topic_id, "action": action})
    body = f"<!-- weekly-checkin\n{payload}\n-->\nSubmitting this logs your answer. It will be auto-closed."
    return build_issue_url(title, body, ["weekly-checkin", "quick"], repo)


def build_freeform_checkin_url(repo):
    title = "\U0001F4AC Weekly check-in: what's on my mind this week"
    payload = json.dumps({"kind": "freeform"})
    body = (
        f"<!-- weekly-checkin\n{payload}\n-->\n"
        f"Reply below this line with whatever's on your mind this week — "
        f"new interests, less of something, anything at all.\n\n"
        f"---\n\n"
        f"(type your answer here, then submit)"
    )
    return build_issue_url(title, body, ["weekly-checkin", "freeform"], repo)


def summarize_week(profile, config):
    recent = tp.recent_feedback(profile, days=7)
    topic_labels = {t["id"]: t["label"] for t in config["topics"]}
    topic_labels["books"] = "books"
    topic_labels["podcasts"] = "podcasts"

    likes = Counter(e["topic"] for e in recent if e["action"] == "like" and e["topic"])
    dislikes = Counter(e["topic"] for e in recent if e["action"] == "dislike" and e["topic"])

    top_topic, top_likes = (likes.most_common(1) or [(None, 0)])[0]
    cool_topic, cool_dislikes = (dislikes.most_common(1) or [(None, 0)])[0]

    lines = [random.choice(OPENERS)]

    if not recent:
        lines.append(NO_DATA_LINE)
    else:
        if top_topic:
            label = topic_labels.get(top_topic, top_topic)
            lines.append(random.choice(TOP_TOPIC_LINES).format(topic=label, likes=top_likes))
        if cool_topic and cool_topic != top_topic:
            label = topic_labels.get(cool_topic, cool_topic)
            lines.append(random.choice(COOL_TOPIC_LINES).format(topic=label, dislikes=cool_dislikes))

    prev_focus = wf.load_weekly_focus()
    if prev_focus.get("ad_hoc_topics"):
        lines.append(random.choice(CALLBACK_LINES).format(topic=prev_focus["ad_hoc_topics"][0]))

    lines.append(random.choice(CLOSERS))

    return " ".join(lines), top_topic, cool_topic, topic_labels


def send_email(message_text, quick_links, freeform_link, dashboard_url):
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")
    to_email = os.environ.get("TO_EMAIL")
    if not (smtp_user and smtp_pass and to_email):
        print("SMTP secrets not set — skipping email, check-in page was still updated.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Weekly check-in — got a sec?"
    msg["From"] = smtp_user
    msg["To"] = to_email

    quick_html = "".join(
        f"<p><a href='{url}'>{label}</a></p>" for label, url in quick_links
    )
    html_body = (
        f"<p>{message_text}</p>"
        f"{quick_html}"
        f"<p><a href='{freeform_link}'>\U0001F4AC Tell me what's on your mind this week</a></p>"
        f"<p><a href='{dashboard_url}'>View your full profile</a></p>"
    )
    text_body = message_text + "\n\n" + "\n".join(f"{label}: {url}" for label, url in quick_links)
    text_body += f"\n\nTell me what's on your mind: {freeform_link}\nFull profile: {dashboard_url}"

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, [to_email], msg.as_string())
    print(f"Weekly check-in sent to {to_email}.")


def generate_checkin_page(message_text, profile, config, generated_at):
    topics_sorted = sorted(profile.get("topics", {}).items(), key=lambda x: x[1], reverse=True)
    creators_sorted = sorted(profile.get("creators", {}).items(), key=lambda x: x[1], reverse=True)

    def rows(pairs, limit=6):
        return "".join(
            f"<tr><td>{name}</td><td class='mono'>{weight:+.1f}</td></tr>"
            for name, weight in pairs[:limit]
        ) or "<tr><td colspan='2'>Nothing learned yet</td></tr>"

    page = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Weekly Check-In</title>
<style>
  body {{ background:#1B2430; color:#EDEFF2; font-family:-apple-system,Segoe UI,sans-serif; padding:32px; max-width:640px; margin:0 auto; }}
  .mono {{ font-family:'IBM Plex Mono',monospace; }}
  h1 {{ font-family:'Space Grotesk',sans-serif; }}
  .msg {{ background:#212C3B; border:1px solid #34435A; border-radius:6px; padding:20px; line-height:1.6; }}
  table {{ width:100%; border-collapse:collapse; margin-top:16px; }}
  td {{ padding:8px; border-bottom:1px solid #34435A; }}
  h2 {{ font-size:16px; color:#9AA6B5; text-transform:uppercase; letter-spacing:.06em; margin-top:32px; }}
</style></head>
<body>
  <h1>Weekly Check-In</h1>
  <p class="mono" style="color:#9AA6B5">{generated_at}</p>
  <div class="msg">{message_text}</div>
  <h2>Topics — what it's learned</h2>
  <table>{rows(topics_sorted)}</table>
  <h2>Creators/sources — what it's learned</h2>
  <table>{rows(creators_sorted)}</table>
</body></html>"""
    os.makedirs(os.path.dirname(CHECKIN_DASHBOARD_PATH), exist_ok=True)
    with open(CHECKIN_DASHBOARD_PATH, "w") as f:
        f.write(page)


def main():
    config = load_config()
    repo = os.environ.get("GITHUB_REPOSITORY", "YOUR-USERNAME/YOUR-REPO")

    profile = tp.load_taste_profile()

    focus = wf.load_weekly_focus()
    focus = wf.decay_and_stamp(focus)  # halve old boosts, clear ad-hoc topics, stamp new week
    wf.save_weekly_focus(focus)

    message_text, top_topic, cool_topic, topic_labels = summarize_week(profile, config)

    quick_links = []
    if top_topic:
        url = build_quick_checkin_url(top_topic, topic_labels.get(top_topic, top_topic), "boost", repo)
        quick_links.append((f"\U0001F44D Yes, more {topic_labels.get(top_topic, top_topic)}", url))
    if cool_topic and cool_topic != top_topic:
        url = build_quick_checkin_url(cool_topic, topic_labels.get(cool_topic, cool_topic), "reduce", repo)
        quick_links.append((f"\U0001F447 Dial back {topic_labels.get(cool_topic, cool_topic)} further", url))

    freeform_link = build_freeform_checkin_url(repo)

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    generate_checkin_page(message_text, profile, config, generated_at)

    dashboard_base = config.get("dashboard_url", "").rstrip("/")
    checkin_url = f"{dashboard_base}/checkin.html" if dashboard_base else ""

    send_email(message_text, quick_links, freeform_link, checkin_url)


if __name__ == "__main__":
    main()
