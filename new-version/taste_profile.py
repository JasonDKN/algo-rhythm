"""
The learning layer. taste_profile.json holds weights the system has learned
from Like/Dislike feedback, separate from the static starting config.

Score for any item = static topic weight (from config.json)
                    + learned topic weight
                    + 0.5 * learned creator weight
                    + 0.3 * learned type weight

Weights decay slightly (2%) every run so the profile keeps adapting rather
than being permanently anchored to old feedback.
"""

import json
import os
from datetime import datetime, timezone

TASTE_PROFILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "taste_profile.json")

DECAY_RATE = 0.98         # applied once per digest run, to every stored weight
WEIGHT_STEP_TOPIC = 3
WEIGHT_STEP_CREATOR = 2
WEIGHT_STEP_TYPE = 1
WEIGHT_CLAMP = 25         # prevents runaway weights from a feedback burst


def _empty_profile():
    return {
        "topics": {}, "creators": {}, "types": {},
        "feedback_log": [],   # rolling list of {topic, action, at} — trimmed to last 200
        "last_updated": None,
    }


def load_taste_profile():
    if not os.path.exists(TASTE_PROFILE_PATH):
        return _empty_profile()
    with open(TASTE_PROFILE_PATH) as f:
        try:
            profile = json.load(f)
        except json.JSONDecodeError:
            return _empty_profile()
    profile.setdefault("feedback_log", [])
    return profile


def save_taste_profile(profile):
    profile["last_updated"] = datetime.now(timezone.utc).isoformat()
    os.makedirs(os.path.dirname(TASTE_PROFILE_PATH), exist_ok=True)
    with open(TASTE_PROFILE_PATH, "w") as f:
        json.dump(profile, f, indent=2)


def apply_decay(profile):
    for bucket in ("topics", "creators", "types"):
        for key in profile.get(bucket, {}):
            profile[bucket][key] = round(profile[bucket][key] * DECAY_RATE, 3)
    return profile


def _clamp(value):
    return max(-WEIGHT_CLAMP, min(WEIGHT_CLAMP, value))


def apply_feedback(profile, topic=None, creator=None, item_type=None, liked=True):
    """Nudge weights up (like) or down (dislike) for the given tags."""
    sign = 1 if liked else -1

    if topic:
        current = profile.setdefault("topics", {}).get(topic, 0)
        profile["topics"][topic] = _clamp(current + sign * WEIGHT_STEP_TOPIC)

    if creator:
        current = profile.setdefault("creators", {}).get(creator, 0)
        profile["creators"][creator] = _clamp(current + sign * WEIGHT_STEP_CREATOR)

    if item_type:
        current = profile.setdefault("types", {}).get(item_type, 0)
        profile["types"][item_type] = _clamp(current + sign * WEIGHT_STEP_TYPE)

    profile.setdefault("feedback_log", []).append({
        "topic": topic, "creator": creator, "type": item_type,
        "action": "like" if liked else "dislike",
        "at": datetime.now(timezone.utc).isoformat(),
    })
    profile["feedback_log"] = profile["feedback_log"][-200:]  # keep it bounded

    return profile


def recent_feedback(profile, days=7):
    cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
    recent = []
    for entry in profile.get("feedback_log", []):
        try:
            ts = datetime.fromisoformat(entry["at"]).timestamp()
        except (KeyError, ValueError):
            continue
        if ts >= cutoff:
            recent.append(entry)
    return recent


def score_item(item, static_topic_weight, profile):
    learned_topic = profile.get("topics", {}).get(item.get("topic", ""), 0)
    learned_creator = profile.get("creators", {}).get(item.get("creator", ""), 0)
    learned_type = profile.get("types", {}).get(item.get("type", ""), 0)

    return (
        static_topic_weight
        + learned_topic
        + 0.5 * learned_creator
        + 0.3 * learned_type
    )
