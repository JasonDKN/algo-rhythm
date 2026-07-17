"""
Generates the "get to know you" question that rides along in every daily
digest email, and the pre-filled GitHub Issue link for the freeform reply.
Rotates deterministically through a question bank by day-of-year, so it's
varied without needing any state of its own.
"""

import json
import urllib.parse
from datetime import date

QUESTION_BANK = [
    "What's something you've been curious about lately that isn't on your list yet?",
    "Any shows, hobbies, or rabbit holes you've fallen into this week?",
    "What's something you'd geek out about if someone brought it up?",
    "Is there a skill, place, or topic you've been quietly into lately?",
    "What's on your mind that has nothing to do with what I already send you?",
    "What did you find yourself looking up or reading about recently, just for fun?",
    "If you had a free afternoon, what would you probably end up doing?",
    "What's something new you tried or discovered recently?",
]


def todays_question():
    day_index = date.today().timetuple().tm_yday
    return QUESTION_BANK[day_index % len(QUESTION_BANK)]


def build_discovery_reply_url(question, repo):
    title = "\U0001F9E9 Daily discovery reply"
    payload = json.dumps({"kind": "daily-discovery"})
    body = (
        f"<!-- daily-discovery\n{payload}\n-->\n"
        f"**Question:** {question}\n\n"
        f"---\n\n"
        f"(type your answer here, then submit)"
    )
    base = f"https://github.com/{repo}/issues/new"
    query = urllib.parse.urlencode({"title": title, "body": body, "labels": "daily-discovery"})
    return f"{base}?{query}"
