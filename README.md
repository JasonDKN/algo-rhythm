# Daily Mix — Personal Content Digest

A daily digest of BTS news/videos, NBA, NFL, Super Smash Bros, Valorant,
world & local news, book picks, and podcasts — scored against a taste
profile that **learns from your 👍/👎 feedback every day**, grows to cover
new interests you mention, checks in with you weekly, and throws in a
daily language phrase for fun.

**Sources (all free, no scraping):** Google News RSS, YouTube Data API,
Google Books API, iTunes Search API, MyMemory Translation API.

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

## 9. Daily discovery — growing beyond your original topics

Every single day, the digest email includes one **"Get to Know You"**
question (`daily_discovery.py` rotates through a bank of ~8 varied
prompts, so it doesn't repeat itself constantly) with a freeform reply
link, same GitHub Issue mechanism as everything else.

`process-daily-discovery.yml` → `daily_discovery_processor.py` reads your
reply and, using the same rule-based clause parsing as the weekly
check-in:
- If a clause mentions a topic already in `config.json`, it **reinforces**
  that topic directly in your permanent taste profile — a stronger signal
  than a passive click, since you said it outright.
- If a clause doesn't match anything you already have, it becomes a
  candidate in **`data/discovered_topics.json`** — a genuinely new,
  persistent topic the app starts fetching content for.

This is deliberately a *third* layer, distinct from the other two:

| File | Scope | Lifespan |
|---|---|---|
| `config.json` | Your original hand-picked topics | Permanent, only changes if you edit it |
| `data/discovered_topics.json` | Topics the app learned about you | Persistent but earns its keep — each has a `confidence` score that grows when its content gets liked and decays daily; anything that drops too low gets pruned automatically (capped at 12 topics so it doesn't grow forever) |
| `data/weekly_focus.json` | This week's stated mood | Deliberately temporary — halves every Sunday |

So mentioning "ceramics" once nudges it in gently; mentioning it again (or
liking the content it generates) grows it; ignoring it lets it fade out on
its own. That's the "learning every day, not just about the original
topics" behavior you asked for.

## 10. Phrase of the Day

Every digest includes one everyday English phrase (rotating daily from
`data/phrase_bank.json`, ~30 phrases) translated into Vietnamese, Korean,
French, Spanish, and Ukrainian.

**Translations come from `data/phrase_translations.json` first** — a
curated, hand-checked table covering all 30 phrases in the current bank —
and only fall back to the live MyMemory Translation API for a phrase that
isn't in that table (e.g. if you add new ones later).

**Why it's built this way — this was a real incident, not a hypothetical:**
during testing, MyMemory translated "I miss you" into French as sexually
explicit text with zero relation to the phrase. MyMemory's translation
memory is aggregated from crowdsourced and scraped bilingual corpora
(including movie/subtitle datasets), so a short, common phrase can
accidentally match a low-confidence, completely unrelated pair from that
pool. The original code trusted whatever came back. It shouldn't have.

Two fixes are now in place:
1. The 30 phrases you're actually using never call the live API at all.
2. If a phrase *does* fall back to MyMemory (new phrases only), any match
   below a strict 0.75 confidence score is rejected outright — you'll see
   "unavailable today" for that language rather than an unvetted guess.

**If you add new phrases to `phrase_bank.json`:** add a matching entry to
`phrase_translations.json` too if you want a guaranteed-safe translation
for it (I'm happy to help translate a batch anytime); otherwise it'll rely
on the confidence-gated live fallback, which is much safer than before but
not absolutely bulletproof.

One more honest note: the curated translations were written by an AI
(me), not verified by a professional translator or native speaker for
every language. They're standard, common phrases with low ambiguity, so
I'm reasonably confident in them, but if you have a native speaker on hand
for Korean or Ukrainian in particular, a sanity check wouldn't hurt.

**To add more languages later:** add an entry to `"languages"` in
`config.json`:
```json
{"code": "ja", "label": "Japanese", "flag": "🇯🇵"}
```
Any phrase without a curated entry for that language code will go through
the same confidence-gated MyMemory fallback.

## 11. Pronunciation — IPA and audio

Each phrase card now shows an IPA transcription and a playable audio clip,
generated with **espeak-ng** (open-source, offline, no API key, no
per-request cost, and — importantly after the translation incident above —
deterministic rather than crowdsourced, so there's no risk of an unrelated
or inappropriate result coming back).

For the current 30-phrase bank, everything is pre-generated and committed
as static assets:
- `data/phrase_ipa.json` — IPA text for all 30 phrases × 5 languages
- `docs/audio/<lang>/<phrase-slug>.mp3` — 150 short audio clips (~2 MB total)

Normal daily runs just read these files — they don't need espeak-ng
installed at all for existing phrases.

**If you add a new phrase to `phrase_bank.json`:** `daily-digest.yml` now
installs `espeak-ng` and `ffmpeg` as a fallback, so `pronunciation.py`
generates the missing IPA + audio on the fly the first time that phrase is
selected, then commits the new files so it's a one-time cost per phrase,
same self-extending pattern as the discovered-topics feature.

**Honest limitation:** espeak-ng's IPA is a speech synthesizer's internal
phonetic approximation, not a linguist's transcription. It's consistent
and safe, but for Vietnamese specifically, tones show up as digits (1–6)
attached to the vowel rather than proper IPA tone diacritics — that's
espeak's own notation convention, not a bug, but worth knowing before
treating it as a formal phonetic reference.

## 12. The visual redesign

The dashboard is now a colorful card grid instead of a plain table:
YouTube thumbnails and book covers render as real images; anything without
a native image (articles, podcasts) gets a colored gradient card with a
topic emoji instead of a blank row. Each topic has its own accent color
(BTS purple, NBA orange, Valorant red, etc.) used consistently across chips,
card borders, and section styling. The email digest got the same treatment
— thumbnails, colored left-borders per topic, and the Phrase of the Day /
Daily Discovery sections included inline.

## 13. Tune it

Everything about *what* gets fetched and *how much* lives in `config.json`:

- `topics` — add/remove topics, edit `news_queries`/`youtube_queries`,
  adjust `static_weight` (how much a topic is favored before any learning)
- `items_per_topic` — how many items per topic per day
- `exclude_keywords` — best-effort political-content filter (exact-phrase
  matching — won't catch every rephrasing, worth reviewing occasionally)
- `clickbait_phrases` — same caveat, heuristic not perfect
- `books.genres`, `podcasts.search_terms`, `podcasts.max_duration_minutes`
- `local_news_location` — currently Calgary, AB
- `languages` — add/remove languages for the Phrase of the Day section

`data/taste_profile.json` is the *learned* layer — you generally shouldn't
need to hand-edit it, but you can reset it to
`{"topics": {}, "creators": {}, "types": {}, "feedback_log": [], "last_updated": null}`
any time you want to start the learning over.

`data/discovered_topics.json` is the *app-grown* layer from daily
discovery replies — reset it to `{"topics": {}}` to clear everything it's
picked up on its own, without touching your original `config.json` topics.

## Local testing

```bash
pip install -r requirements.txt
export YOUTUBE_API_KEY=your_key_here   # optional locally; skips YouTube results if unset
python digest.py
```

Without `SMTP_USER`/`SMTP_PASS`/`TO_EMAIL` set, it still fetches, scores,
and rebuilds the dashboard — it just skips sending email.
