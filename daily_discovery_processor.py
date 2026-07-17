#!/usr/bin/env python3
"""
Runs when a daily-discovery issue is opened (see .github/workflows/process-daily-discovery.yml).

Same rule-based clause parsing approach as the weekly check-in (no LLM):
splits the reply into clauses, checks each against config.json's known
topics. A match reinforces that topic directly in the permanent taste
profile (this is an explicit self-report, a stronger signal than a click).
Anything unmatched becomes a candidate in data/discovered_topics.json —
the app's genuinely-growing, app-learned topic list.
"""

import os
import re
import json

import requests
import taste_profile as tp
import discovered_topics as dt

GITHUB_API = "https://api.github.com"
DISCOVERY_RE = re.compile(r"<!--\s*daily-discovery\s*(\{.*?\})\s*-->", re.DOTALL)
CLAUSE_SPLIT_RE = re.compile(r",| and | but |;|\n|\.(?=\s|$)")

REINFORCE_STEP = 4  # stronger than a passive like (3), since this is self-reported


def load_config():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    with open(path) as f:
        return json.load(f)


def get_topic_keyword_map(config):
    kw_map = {}
    for t in config["topics"]:
        keywords = {t["label"].lower(), t["id"].lower()}
        keywords.update(q.lower() for q in t.get("news_queries", []))
        keywords.update(q.lower() for q in t.get("youtube_queries", []))
        kw_map[t["id"]] = keywords
    return kw_map


def extract_reply_text(issue_body):
    if "---" in issue_body:
        after = issue_body.split("---", 1)[1]
    else:
        after = issue_body
    return after.replace("(type your answer here, then submit)", "").strip()


def parse_reply(text, config):
    kw_map = get_topic_keyword_map(config)
    clauses = [c.strip() for c in CLAUSE_SPLIT_RE.split(text) if c.strip()]

    known_matches = []
    new_phrases = []

    for clause in clauses:
        lower = clause.lower()
        matched_topic = None
        for topic_id, keywords in kw_map.items():
            if any(kw in lower for kw in keywords if len(kw) > 2):
                matched_topic = topic_id
                break
        if matched_topic:
            known_matches.append(matched_topic)
        elif clause and 3 <= len(clause) < 80:
            new_phrases.append(clause)

    return known_matches, new_phrases[:3]


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

    if not DISCOVERY_RE.search(issue_body):
        print("No daily-discovery payload found — ignoring.")
        return

    reply_text = extract_reply_text(issue_body)
    if not reply_text:
        close_issue(repo, issue_number, token, "Didn't catch any text in that reply — no changes made.")
        return

    config = load_config()
    known_matches, new_phrases = parse_reply(reply_text, config)

    profile = tp.load_taste_profile()
    for topic_id in known_matches:
        profile = tp.apply_feedback(profile, topic=topic_id, liked=True)
        profile["topics"][topic_id] = profile["topics"].get(topic_id, 0) + (REINFORCE_STEP - 3)  # extra nudge
    tp.save_taste_profile(profile)

    discovered = dt.load_discovered_topics()
    added_labels = []
    for phrase in new_phrases:
        discovered, topic_id = dt.add_or_reinforce(discovered, phrase)
        added_labels.append(phrase)
    dt.save_discovered_topics(discovered)

    parts = []
    if known_matches:
        parts.append(f"reinforced your interest in {', '.join(f'`{t}`' for t in known_matches)}")
    if added_labels:
        parts.append(f"added {', '.join(f'`{p}`' for p in added_labels)} to your growing topic list")
    comment = "Got it — " + (" and ".join(parts) if parts else "noted, but nothing specific jumped out to act on") + \
              ". New topics start light and grow into your digest as they keep coming up."

    close_issue(repo, issue_number, token, comment)
    print(f"Processed daily discovery: known={known_matches} new={added_labels}")


if __name__ == "__main__":
    main()
