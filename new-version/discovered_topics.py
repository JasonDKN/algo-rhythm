"""
data/discovered_topics.json holds topics the app has learned about through
daily discovery answers — separate from:
  - config.json's topics: your original, permanent, hand-picked list
  - weekly_focus.json: this week's temporary boosts, which fade fast

Discovered topics are meant to persist longer than a weekly whim but still
need to earn their keep: each has a `confidence` score that rises when its
content gets liked, falls when disliked or repeatedly ignored, and topics
that drop too low get pruned automatically so the topic list doesn't grow
forever.
"""

import json
import os
import re
from datetime import datetime, timezone

DISCOVERED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "discovered_topics.json")

STARTING_CONFIDENCE = 5
PRUNE_THRESHOLD = -3
DAILY_DECAY = 0.97   # gentle decay applied once per digest run
MAX_DISCOVERED_TOPICS = 12   # keeps things from growing without bound


def _slugify(text):
    return "disc_" + re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40]


def load_discovered_topics():
    if not os.path.exists(DISCOVERED_PATH):
        return {"topics": {}}
    with open(DISCOVERED_PATH) as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {"topics": {}}


def save_discovered_topics(data):
    os.makedirs(os.path.dirname(DISCOVERED_PATH), exist_ok=True)
    with open(DISCOVERED_PATH, "w") as f:
        json.dump(data, f, indent=2)


def add_or_reinforce(data, phrase):
    """Called when the user mentions a topic in a daily discovery reply."""
    topic_id = _slugify(phrase)
    topics = data.setdefault("topics", {})

    if topic_id in topics:
        topics[topic_id]["confidence"] = min(20, topics[topic_id]["confidence"] + 3)
        topics[topic_id]["last_mentioned"] = datetime.now(timezone.utc).isoformat()
    else:
        if len(topics) >= MAX_DISCOVERED_TOPICS:
            # bump out the weakest existing topic to make room
            weakest_id = min(topics, key=lambda k: topics[k]["confidence"])
            if topics[weakest_id]["confidence"] < STARTING_CONFIDENCE:
                del topics[weakest_id]
            else:
                return data, topic_id  # everything is doing well; don't evict, just skip adding
        topics[topic_id] = {
            "label": phrase,
            "confidence": STARTING_CONFIDENCE,
            "added": datetime.now(timezone.utc).isoformat(),
            "last_mentioned": datetime.now(timezone.utc).isoformat(),
        }
    return data, topic_id


def adjust_confidence(data, topic_id, delta):
    topics = data.get("topics", {})
    if topic_id in topics:
        topics[topic_id]["confidence"] = round(topics[topic_id]["confidence"] + delta, 2)
    return data


def decay_and_prune(data):
    topics = data.get("topics", {})
    for tid in list(topics):
        topics[tid]["confidence"] = round(topics[tid]["confidence"] * DAILY_DECAY, 2)
        if topics[tid]["confidence"] < PRUNE_THRESHOLD:
            del topics[tid]
    return data
