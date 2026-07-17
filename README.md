# Daily Mix — Personal Content Digest

A daily digest of BTS news/videos, NBA, NFL, Super Smash Bros, Valorant,
world & local news, book picks, and podcasts — scored against a taste
profile that **learns from your 👍/👎 feedback every day.**

**Sources (all free, no scraping):** Google News RSS, YouTube Data API,
Google Books API, iTunes Search API.

## 1. Create the repo

Push everything in this folder to a new GitHub repository (public, unless
you have GitHub Pro/Team/Enterprise — Pages needs a public repo on the free
tier).

## 2. Turn on GitHub Pages

Settings → Pages → **Source: Deploy from a branch** → Branch: `main`,
folder: `/docs` → Save. Your dashboard: `https://<username>.github.io/<repo>/`.

Set that URL as `dashboard_url` in `config.json`.

## 3. Get a YouTube API key (free)

1. Go to [console.cloud.google.com](https://console.cloud.google.com) → create a project.
2. Enable the **YouTube Data API v3**.
3. Credentials → Create Credentials → API key.
4. The free daily quota (10,000 units) comfortably covers this app's usage
   (~15 searches/day = 1,500 units).

## 4. Gmail App Password (for the email digest)

Same as before: turn on 2-Step Verification, then generate an app password
at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).

## 5. Add repository secrets

Settings → Secrets and variables → Actions → New repository secret:

| Secret            | Value                          |
|-------------------|----------------------------------|
| `SMTP_USER`       | your Gmail address              |
| `SMTP_PASS`       | Gmail app password               |
| `TO_EMAIL`        | where the digest should go       |
| `YOUTUBE_API_KEY` | the API key from step 3          |

`GITHUB_TOKEN` is provided automatically by Actions — no setup needed, but
double check under Settings → Actions → General → Workflow permissions that
**"Read and write permissions"** is selected, or the feedback workflow won't
be able to close issues or commit.

## 6. Test it

Actions tab → "Daily Content Digest" → **Run workflow**. Check it goes
green, then look at your Pages URL.

## 7. How the feedback loop works

Every item in the dashboard/email has 👍 / 👎 links. Clicking one opens a
**pre-filled GitHub Issue** in your repo — this is the only way to trigger
an action from a static site + email with no server. You'll need to click
GitHub's "Submit new issue" button once to confirm (this is a GitHub
requirement, not something I can skip).

Once submitted, the `process-feedback.yml` workflow fires automatically:
it reads the embedded feedback data, updates `data/taste_profile.json`
(topic/creator/content-type weights), closes the issue, and comments
confirming what was logged. Tomorrow's digest scoring includes those
learned weights on top of your static starting preferences in
`config.json` — and old feedback gently decays (2%/day) so the profile
keeps adapting rather than calcifying around early clicks.

A wildcard pick from outside your top topics is included in every digest
on purpose, so the feed doesn't collapse into an echo chamber.

## 8. The weekly check-in

Every Sunday (`weekly-checkin.yml`), `weekly_checkin.py` looks at the past
week's Like/Dislike activity and emails you a casual summary — what topic
you were clearly into, what you kept skipping — plus:

- 1-2 tap-to-answer links ("Yes, more BTS" / "Dial back Valorant further")
- one open-ended link where you type freely about what's actually on your
  mind that week

Your reply is processed by `process-weekly-checkin.yml` →
`weekly_checkin_processor.py`, which updates `data/weekly_focus.json` — a
**temporary** layer of boosts separate from the permanent learned profile
in `data/taste_profile.json`. It fades on its own (halved every Sunday) so
a passing interest doesn't permanently warp your profile.

**How the free-text reply is understood — read this before relying on it:**
This was built **rule-based, not LLM-based** (your choice, to avoid an
extra API key/cost). It works by:
1. Splitting your reply into clauses.
2. Checking each clause against the topic keywords already in `config.json`.
   If it recognizes a topic, it checks for a nearby negation word ("less",
   "not really", "tired of", "skip", "over", "no more") to decide boost vs.
   reduce.
3. Anything it doesn't recognize as an existing topic gets treated as a
   literal one-off search topic for that week (capped at 3), rather than
   being guessed at semantically.

This means it's genuinely good at "less Valorant, more BTS" and genuinely
bad at anything requiring real inference (sarcasm, indirect references,
"the thing I mentioned last month"). It also can't invent smart search
queries for a brand-new interest — it just searches the literal phrase you
typed. If that turns out to be too limiting, this is the one piece of the
app where switching to the Claude-API version later would clearly earn its
keep — happy to build that swap if you change your mind.

Full profile summary (all-time learned weights, not just this week): see
`docs/checkin.html`, linked from the bottom of the main dashboard.

## 9. Tune it

Everything about *what* gets fetched and *how much* lives in `config.json`:

- `topics` — add/remove topics, edit `news_queries`/`youtube_queries`,
  adjust `static_weight` (how much a topic is favored before any learning)
- `items_per_topic` — how many items per topic per day
- `exclude_keywords` — best-effort political-content filter (exact-phrase
  matching — won't catch every rephrasing, worth reviewing occasionally)
- `clickbait_phrases` — same caveat, heuristic not perfect
- `books.genres`, `podcasts.search_terms`, `podcasts.max_duration_minutes`
- `local_news_location` — currently Calgary, AB

`data/taste_profile.json` is the *learned* layer — you generally shouldn't
need to hand-edit it, but you can reset it to
`{"topics": {}, "creators": {}, "types": {}, "last_updated": null}`
any time you want to start the learning over.

## Local testing

```bash
pip install -r requirements.txt
export YOUTUBE_API_KEY=your_key_here   # optional locally; skips YouTube results if unset
python digest.py
```

Without `SMTP_USER`/`SMTP_PASS`/`TO_EMAIL` set, it still fetches, scores,
and rebuilds the dashboard — it just skips sending email.
