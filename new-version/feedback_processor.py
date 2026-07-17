#!/usr/bin/env python3
"""
Runs when a Like/Dislike issue is opened (see .github/workflows/process-feedback.yml).
Reads the issue via the GitHub API, extracts the embedded feedback JSON,
updates taste_profile.json, then closes the issue with a confirmation comment.
"""

import os
import re
import json
import sys

import requests
import taste_profile as tp

GITHUB_API = "https://api.github.com"
FEEDBACK_RE = re.compile(r"<!--\s*digest-feedback\s*(\{.*?\})\s*-->", re.DOTALL)


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

    match = FEEDBACK_RE.search(issue_body)
    if not match:
        print("No digest-feedback payload found in issue body — ignoring (not a digest feedback issue).")
        return

    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as e:
        print(f"Could not parse feedback payload: {e}")
        return

    liked = payload.get("action") == "like"
    profile = tp.load_taste_profile()
    profile = tp.apply_feedback(
        profile,
        topic=payload.get("topic"),
        creator=payload.get("creator"),
        item_type=payload.get("type"),
        liked=liked,
    )
    tp.save_taste_profile(profile)

    verdict = "liked" if liked else "disliked"
    comment = (
        f"Got it — logged as **{verdict}** "
        f"(topic: `{payload.get('topic')}`, creator: `{payload.get('creator')}`, type: `{payload.get('type')}`). "
        f"Your taste profile has been updated."
    )
    close_issue(repo, issue_number, token, comment)
    print(f"Processed feedback: {payload}")


if __name__ == "__main__":
    main()
