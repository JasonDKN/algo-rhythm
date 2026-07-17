"""
data/weekly_focus.json holds THIS WEEK's stated interests — separate from
the permanent taste_profile.json. It's meant to fade: every time the weekly
check-in runs, old boosts are halved before new ones are (possibly) added,
so an unanswered check-in fades out over a couple of weeks instead of
sticking around forever or vanishing instantly.
"""

import json
import os
from datetime import datetime, timezone

WEEKLY_FOCUS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "weekly_focus.json")

MAX_AD_HOC_TOPICS = 3
BOOST_STEP = 4


def _empty_focus():
    return {"week_of": None, "topic_boosts": {}, "ad_hoc_topics": [], "last_reply_summary": None}


def load_weekly_focus():
    if not os.path.exists(WEEKLY_FOCUS_PATH):
        return _empty_focus()
    with open(WEEKLY_FOCUS_PATH) as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return _empty_focus()


def save_weekly_focus(focus):
    os.makedirs(os.path.dirname(WEEKLY_FOCUS_PATH), exist_ok=True)
    with open(WEEKLY_FOCUS_PATH, "w") as f:
        json.dump(focus, f, indent=2)


def decay_and_stamp(focus):
    """Called at the start of every weekly check-in run: halve old boosts,
    drop ad-hoc topics (they were only ever meant to last one week), stamp
    the new week."""
    for key in list(focus.get("topic_boosts", {})):
        focus["topic_boosts"][key] = round(focus["topic_boosts"][key] * 0.5, 2)
        if abs(focus["topic_boosts"][key]) < 0.5:
            del focus["topic_boosts"][key]
    focus["ad_hoc_topics"] = []
    focus["week_of"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return focus


def apply_boost(focus, topic, positive):
    sign = 1 if positive else -1
    current = focus.setdefault("topic_boosts", {}).get(topic, 0)
    focus["topic_boosts"][topic] = round(current + sign * BOOST_STEP, 2)
    return focus


def add_ad_hoc_topic(focus, text):
    text = text.strip()
    if not text:
        return focus
    existing = focus.setdefault("ad_hoc_topics", [])
    if text.lower() not in [t.lower() for t in existing] and len(existing) < MAX_AD_HOC_TOPICS:
        existing.append(text)
    return focus
