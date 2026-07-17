#!/usr/bin/env python3
"""
Runs when a weekly-checkin issue is opened (see .github/workflows/process-weekly-checkin.yml).

Two kinds of replies:
  - "quick": a single pre-filled boost/reduce click — just apply it.
  - "freeform": the user typed their own text. This is parsed with simple,
    transparent rules — NOT an LLM:
      1. Split the reply into clauses (commas / " and " / " but " / sentences).
      2. For each clause, check if it contains a known topic's keywords.
         If a negation word ("less", "not", "tired of", "skip", "over",
         "no more") appears in the same clause -> reduce that topic.
         Otherwise -> boost that topic.
      3. Any clause that doesn't match a known topic is treated as a literal
         ad-hoc search topic for the week (capped at 3), rather than guessed at.

This will miss cleverly-phrased or indirect requests — it's pattern matching,
not language understanding. That trade-off was chosen deliberately to avoid
an LLM API dependency/cost; see README for details.
"""

import os
import re
import json

import requests
import taste_profile as tp
import weekly_focus as wf

GITHUB_API = "https://api.github.com"
CHECKIN_RE = re.compile(r"<!--\s*weekly-checkin\s*(\{.*?\})\s*-->", re.DOTALL)

NEGATION_WORDS = [
    "less", "not really", "tired of", "skip", "over ", "no more",
    "done with", "burnt out on", "away from", "reduce",
]

CLAUSE_SPLIT_RE = re.compile(r",| and | but |;|\n|\.(?=\s|$)")


def load_config():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    with open(path) as f:
        return json.load(f)


def get_topic_keyword_map(config):
    """topic_id -> list of lowercase keywords to look for in free text."""
    kw_map = {}
    for t in config["topics"]:
        keywords = {t["label"].lower(), t["id"].lower()}
        keywords.update(q.lower() for q in t.get("news_queries", []))
        keywords.update(q.lower() for q in t.get("youtube_queries", []))
        kw_map[t["id"]] = keywords
    return kw_map


def parse_freeform_reply(text, config):
    """Returns (topic_boosts: {topic_id: bool_positive}, ad_hoc_topics: [str])."""
    kw_map = get_topic_keyword_map(config)
    clauses = [c.strip() for c in CLAUSE_SPLIT_RE.split(text) if c.strip()]

    topic_signals = {}
    ad_hoc = []

    for clause in clauses:
        lower = clause.lower()
        matched_topic = None
        for topic_id, keywords in kw_map.items():
            if any(kw in lower for kw in keywords if len(kw) > 2):
                matched_topic = topic_id
                break

        if matched_topic:
            is_negative = any(neg in lower for neg in NEGATION_WORDS)
            topic_signals[matched_topic] = not is_negative
        else:
            if clause and len(clause) < 80:
                ad_hoc.append(clause)

    return topic_signals, ad_hoc[:3]


def extract_reply_text(issue_body):
    """Pull whatever the user typed after the '---' divider in the template."""
    if "---" in issue_body:
        after = issue_body.split("---", 1)[1]
    else:
        after = issue_body
    after = after.replace("(type your answer here, then submit)", "")
    return after.strip()


def get_issue(repo, issue_number, token):
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    r = requests.get(f"{GITHUB_API}/repos/{repo}/issues/{issue_number}", headers=headers, timeout=20)
    r.raise_for_status()
    return r.json()


def close_issue(repo, issue_number, token, comment):
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    requests.post(
        f"{GITHUB_API}/repos/{repo}/issues/{issue_number}/comments",
        headers=headers, json={"body": comment}, timeout=20,
    )
    requests.patch(
        f"{GITHUB_API}/repos/{repo}/issues/{issue_number}",
        headers=headers, json={"state": "closed"}, timeout=20,
    )


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GITHUB_TOKEN"]
    issue_number = os.environ["ISSUE_NUMBER"]
    issue_body = os.environ.get("ISSUE_BODY", "")

    match = CHECKIN_RE.search(issue_body)
    if not match:
        print("No weekly-checkin payload found — ignoring.")
        return

    payload = json.loads(match.group(1))
    config = load_config()
    focus = wf.load_weekly_focus()

    if payload.get("kind") == "quick":
        topic = payload.get("topic")
        positive = payload.get("action") == "boost"
        focus = wf.apply_boost(focus, topic, positive)
        wf.save_weekly_focus(focus)
        comment = f"Got it — {'leaning into' if positive else 'easing off'} `{topic}` this week."

    elif payload.get("kind") == "freeform":
        reply_text = extract_reply_text(issue_body)
        if not reply_text:
            close_issue(repo, issue_number, token, "Didn't catch any text in that reply — no changes made.")
            print("Empty freeform reply.")
            return

        topic_signals, ad_hoc = parse_freeform_reply(reply_text, config)
        for topic_id, positive in topic_signals.items():
            focus = wf.apply_boost(focus, topic_id, positive)
        for phrase in ad_hoc:
            focus = wf.add_ad_hoc_topic(focus, phrase)
        focus["last_reply_summary"] = reply_text[:200]
        wf.save_weekly_focus(focus)

        parts = []
        if topic_signals:
            parts.append(", ".join(
                f"{'more' if pos else 'less'} `{t}`" for t, pos in topic_signals.items()
            ))
        if ad_hoc:
            parts.append("added as a new one-off topic this week: " + ", ".join(f"`{a}`" for a in ad_hoc))
        comment = "Got it — " + (" and ".join(parts) if parts else "noted, though nothing jumped out to act on yet") + "."

    else:
        print(f"Unknown weekly-checkin kind: {payload.get('kind')}")
        return

    close_issue(repo, issue_number, token, comment)
    print(f"Processed weekly check-in: {payload}")


if __name__ == "__main__":
    main()
