"""
HAIC 2026 – Team Kahu Ola – the message library for the app's Messages tab.

Reads every row of data/sources/messages/*.csv. Readers see a neutral review status:
"Reviewed" only when the language has a native-speaker reviewer in config/communication.json
(message_library.language_review.<language>.reviewed_by) and the row is approved with a named
reviewer and a review date; every other row with text is "Draft — needs review by a native
speaker before use".
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MESSAGES = ROOT / "data" / "sources" / "messages"
REPO = "https://github.com/HAIC-2026/Kahu-Ola"
SOURCES_URL = f"{REPO}/blob/main/PLAN.md#3-data-sources-and-dates"
PHASES = {"pre": "Before", "evac": "Evacuate", "shelter": "Shelter open"}
LANG_TAG = {"English": "en", "Spanish": "es", "Tagalog, Filipino": "tl", "Chinese": "zh-Hant",
            "Japanese": "ja", "Korean": "ko", "Vietnamese": "vi", "Ilocano": "ilo",
            "Hawaiian": "haw", "Other English-based Creole languages": "hwc",
            "Chuukese": "chk", "Marshallese": "mh"}
LANG_LABEL = {"Other English-based Creole languages": "Pidgin (Hawaiʻi Creole English)",
              "Tagalog, Filipino": "Tagalog/Filipino"}


def load_messages(folder: Path = MESSAGES) -> list:
    """Every row of every message file, stored values unchanged."""
    rows = []
    for path in sorted(folder.glob("*.csv")):
        with open(path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                rows.append({**r, "file": f"data/sources/messages/{path.name}"})
    return rows


def is_draft(r: dict) -> bool:
    return r["status"].startswith("DRAFT") and bool(r["text"].strip())


def is_placeholder(r: dict) -> bool:
    return r["status"].startswith("NEEDS HUMAN TRANSLATION") and not r["text"].strip()


def message_counts(rows: list) -> list:
    """Per language: rows, drafts, rows waiting for a translator, reviewed, assignee."""
    out = {}
    for r in rows:
        c = out.setdefault(r["language"], {"language": r["language"],
                                           "label": LANG_LABEL.get(r["language"], r["language"]),
                                           "rows": 0, "drafts": 0,
                                           "placeholders": 0, "reviewed": 0, "assignee": ""})
        c["rows"] += 1
        c["drafts"] += is_draft(r)
        c["placeholders"] += is_placeholder(r)
        c["reviewed"] += review_status(r) == REVIEWED
        c["assignee"] = c["assignee"] or r["review_assignee"]
    return sorted(out.values(), key=lambda c: (c["language"] != "English", c["language"]))


REVIEWED = "Reviewed"
DRAFT = "Draft — needs review by a native speaker before use"
CONFIG = ROOT / "config" / "communication.json"


def language_review(path: Path = CONFIG) -> dict:
    """language -> {"reviewed_by", "review_date"} (empty until a native speaker has reviewed)."""
    import json
    return json.loads(path.read_text(encoding="utf-8"))["message_library"]["language_review"]


def language_reviewed(language: str, review: dict | None = None) -> bool:
    review = language_review() if review is None else review
    return bool((review.get(language) or {}).get("reviewed_by", "").strip())
NEEDS_TRANSLATOR = "Needs a translator"
NOTE_HIDDEN = re.compile(r"\bAI\b|Claude|model output", re.I)


def review_status(r: dict, review: dict | None = None) -> str:
    """'Reviewed' only when the language has a native-speaker reviewer (config) and the row is
    approved with a named reviewer and a review date; a row with no text yet is 'Needs a
    translator'; everything else is a draft."""
    ok = (r["approved"].strip().lower() == "yes" and r["reviewed_by"].strip()
          and r["review_date"].strip() and language_reviewed(r["language"], review))
    if ok:
        return REVIEWED
    return NEEDS_TRANSLATOR if not r.get("text", "").strip() else DRAFT


TRIGGERS = ROOT / "config" / "decision_points.json"


def trigger_names(path: Path = TRIGGERS) -> dict:
    """Trigger id -> official product name ("hurricane_watch" -> "Hurricane Watch")."""
    import json
    trig = json.loads(path.read_text(encoding="utf-8"))["triggers"]
    return {k: v["product"] for k, v in trig.items()}


def messages_line(rows: list | None = None) -> str:
    """The PDF and app line about message languages, with each language's review state."""
    rows = load_messages() if rows is None else rows
    counts = [c for c in message_counts(rows) if c["language"] != "English"]
    def names(cs):
        n = sorted(LANG_LABEL.get(c["language"], c["language"]).split(" (")[0].split("/")[0] for c in cs)
        return n[0] if len(n) == 1 else ", ".join(n[:-1]) + " and " + n[-1]
    drafts = [c for c in counts if c["drafts"] and c["reviewed"] < c["rows"]]
    done = [c for c in counts if c["rows"] and c["reviewed"] == c["rows"]]
    waiting = [c for c in counts if c["placeholders"]]
    out = []
    if drafts:
        out.append(f"Draft messages are available statewide in {names(drafts)}: {DRAFT}.")
    if done:
        out.append(f"Reviewed by a native speaker: {names(done)}.")
    if waiting:
        out.append(f"{names(waiting)} need{'s' if len(waiting) == 1 else ''} translators.")
    return " ".join(out)


def bundle_messages(rows: list | None = None) -> list:
    """Message rows for the app: text and review fields, neutral status."""
    rows = load_messages() if rows is None else rows
    names = trigger_names()
    out = []
    for r in rows:
        out.append({
            "message_id": r["message_id"], "hazard": r["hazard"], "trigger": r["trigger"],
            "timing": r["timing"], "channel": r["channel"], "language": r["language"],
            "text": r["text"], "status": review_status(r),
            "review_assignee": r["review_assignee"], "reviewed_by": r["reviewed_by"],
            "review_date": r["review_date"], "approved": r["approved"],
            "notes": "" if NOTE_HIDDEN.search(r["notes"]) else r["notes"],
            "phase": PHASES.get(r["message_id"].rsplit("-", 1)[-1], r["timing"]),
            "lang": LANG_TAG.get(r["language"], ""),
            "trigger_label": names.get(r["trigger"], r["trigger"].replace("_", " ").title()),
            "language_label": LANG_LABEL.get(r["language"], r["language"]),
            "file": r["file"],
        })
    return out
