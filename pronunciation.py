"""
Pronunciation support for the Phrase of the Day feature: IPA transcriptions
and audio clips, generated with espeak-ng (open-source, offline, no API key,
no per-request cost or ToS risk).

For the current 30-phrase bank, everything is pre-generated as static
assets: data/phrase_ipa.json (text) and docs/audio/<lang>/<slug>.mp3
(audio) — committed to the repo, so normal daily runs don't need espeak-ng
installed at all.

If you add a NEW phrase to phrase_bank.json without pre-generating assets
for it, generate_missing() below will synthesize IPA + audio on the fly
during the Actions run (espeak-ng is installed in daily-digest.yml for
exactly this reason) and commit the new files back to the repo, so it
only ever needs to happen once per new phrase.

Honest limitation: espeak-ng's IPA output is a rule-based synthesizer's
internal approximation, not a linguist's transcription. It's consistent
and won't produce anything inappropriate (it's deterministic, not
crowdsourced, so it doesn't carry the risk the translation API had) — but
for tonal languages like Vietnamese, it represents tones as digits (1-6)
attached to the vowel rather than proper IPA tone diacritics, since that's
espeak's internal convention. Treat the IPA as a rough pronunciation guide
rather than an academic transcription.
"""

import json
import os
import re
import shutil
import subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))
IPA_PATH = os.path.join(ROOT, "data", "phrase_ipa.json")
AUDIO_DIR = os.path.join(ROOT, "docs", "audio")

ESPEAK_AVAILABLE = shutil.which("espeak-ng") is not None and shutil.which("ffmpeg") is not None


def slugify(phrase):
    return re.sub(r"[^a-z0-9]+", "_", phrase.lower()).strip("_")[:40]


def load_ipa_table():
    if not os.path.exists(IPA_PATH):
        return {}
    try:
        with open(IPA_PATH) as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}


def save_ipa_table(table):
    os.makedirs(os.path.dirname(IPA_PATH), exist_ok=True)
    with open(IPA_PATH, "w") as f:
        json.dump(table, f, ensure_ascii=False, indent=2)


def audio_path_for(phrase, lang_code):
    """Relative path (from docs/) to the audio file, for linking in the dashboard."""
    slug = slugify(phrase)
    return f"audio/{lang_code}/{slug}.mp3"


def _generate_ipa(text, lang_code):
    try:
        result = subprocess.run(
            ["espeak-ng", "-v", lang_code, "--ipa", "-q", text],
            capture_output=True, text=True, timeout=15,
        )
        return result.stdout.strip()
    except Exception as e:
        print(f"[pronunciation] IPA generation failed for {lang_code}: {e}")
        return ""


def _generate_audio(text, lang_code, phrase):
    slug = slugify(phrase)
    lang_dir = os.path.join(AUDIO_DIR, lang_code)
    os.makedirs(lang_dir, exist_ok=True)
    wav_path = os.path.join(lang_dir, f"{slug}.wav")
    mp3_path = os.path.join(lang_dir, f"{slug}.mp3")
    try:
        subprocess.run(["espeak-ng", "-v", lang_code, "-s", "150", "-w", wav_path, text],
                        capture_output=True, timeout=15, check=True)
        subprocess.run(["ffmpeg", "-y", "-i", wav_path, "-codec:a", "libmp3lame", "-qscale:a", "4", mp3_path],
                        capture_output=True, timeout=15, check=True)
        os.remove(wav_path)
        return True
    except Exception as e:
        print(f"[pronunciation] Audio generation failed for {lang_code}: {e}")
        return False


def get_pronunciation(phrase, lang_code, text):
    """Returns (ipa_string, audio_relative_path_or_empty). Uses the curated
    table/pre-generated file if present; generates on the fly (and persists)
    only if missing and espeak-ng is available."""
    table = load_ipa_table()
    ipa = table.get(phrase, {}).get(lang_code, "")

    audio_rel = audio_path_for(phrase, lang_code)
    audio_full_path = os.path.join(ROOT, "docs", audio_rel)
    has_audio = os.path.exists(audio_full_path)

    if ipa and has_audio:
        return ipa, audio_rel

    if not ESPEAK_AVAILABLE:
        return ipa, (audio_rel if has_audio else "")

    if not ipa:
        ipa = _generate_ipa(text, lang_code)
        table.setdefault(phrase, {})[lang_code] = ipa
        save_ipa_table(table)

    if not has_audio:
        has_audio = _generate_audio(text, lang_code, phrase)

    return ipa, (audio_rel if has_audio else "")
