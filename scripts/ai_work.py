"""
HAIC 2026 – Team Kahu Ola – what AI did in this project, computed at build time.

Shared by build_playbooks.py (section 9 of every playbook) and build_app_data.py
(the app's Messages tab and "How AI built this plan" page). Nothing here calls a
network service or an AI model: it reads the repository files and git history.
Every count is computed; none is typed in.
"""
from __future__ import annotations

import csv
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MESSAGES = ROOT / "data" / "sources" / "messages"
SHELTERS = ROOT / "data" / "sources" / "county_shelter_activations.csv"
REPO = "https://github.com/HAIC-2026/Kahu-Ola"
LINKS = {
    "shelters": f"{REPO}/blob/main/data/sources/county_shelter_activations.csv",
    "sources": f"{REPO}/blob/main/PLAN.md#3-data-sources-and-dates",
    "commits": f"{REPO}/commits/main",
    "messages": f"{REPO}/tree/main/data/sources/messages",
}
PHASES = {"pre": "Before", "evac": "Evacuate", "shelter": "Shelter open"}
LANG_TAG = {"English": "en", "Spanish": "es", "Tagalog, Filipino": "tl", "Chinese": "zh-Hant",
            "Japanese": "ja", "Korean": "ko", "Vietnamese": "vi", "Ilocano": "ilo",
            "Hawaiian": "haw", "Other English-based Creole languages": "hwc",
            "Chuukese": "chk", "Marshallese": "mh"}
LANG_LABEL = {"Other English-based Creole languages": "Pidgin (Hawaiʻi Creole English)",
              "Tagalog, Filipino": "Tagalog/Filipino"}
NOT_DONE = [
    ("Compute the numbers",
     "Every count and estimate is calculated by open, deterministic code from public data "
     "(the scripts/ folder in the repository)."),
    ("Decide shelter status",
     "Usable / check / not for this hazard comes from fixed rules on official FEMA flood maps "
     "and State tsunami evacuation zones."),
    ("Run during an emergency",
     "The app and playbooks work offline. No AI runs at that time and no live data is fetched."),
]


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
    """Per language: rows, AI drafts, placeholders, approved, review assignee."""
    out = {}
    for r in rows:
        c = out.setdefault(r["language"], {"language": r["language"],
                                           "label": LANG_LABEL.get(r["language"], r["language"]),
                                           "rows": 0, "drafts": 0,
                                           "placeholders": 0, "approved": 0, "assignee": ""})
        c["rows"] += 1
        c["drafts"] += is_draft(r)
        c["placeholders"] += is_placeholder(r)
        c["approved"] += r["approved"].strip().lower() == "yes"
        c["assignee"] = c["assignee"] or r["review_assignee"]
    return sorted(out.values(), key=lambda c: (c["language"] != "English", c["language"]))


def git_stats(root: Path = ROOT) -> dict:
    """Commit count, commits co-authored by Claude, and HEAD, from git history."""
    def git(*args):
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                              text=True, check=True).stdout
    try:
        bodies = git("log", "--format=%B%x00").split("\x00")
        commits = int(git("rev-list", "--count", "HEAD").strip())
        head = git("rev-parse", "--short", "HEAD").strip()
    except (OSError, subprocess.CalledProcessError, ValueError):
        return {"commits": None, "coauthored": None, "head": ""}
    co = sum(1 for b in bodies if re.search(r"^Co-Authored-By: Claude", b, re.M | re.I))
    return {"commits": commits, "coauthored": co, "head": head}


def test_count(root: Path = ROOT) -> int:
    """Same discovery as `python3 -m unittest discover tests`."""
    return unittest.TestLoader().discover(str(root / "tests")).countTestCases()


def shelter_stats(path: Path = SHELTERS) -> dict:
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    official = ("kauai.gov", "honolulu.gov", "mauicounty.gov", "hawaiicounty.gov", "hawaii.gov")
    return {"rows": len(rows),
            "official_rows": sum(any(d in r["source_url"] for d in official) for r in rows)}


def n(v) -> str:
    return "not available" if v is None else f"{v:,}"


def summary(rows: list | None = None) -> dict:
    """All build-time facts for the AI page and playbook section 9."""
    rows = load_messages() if rows is None else rows
    counts = message_counts(rows)
    translated = [c["language"] for c in counts if c["language"] != "English" and c["drafts"]]
    human = [c["language"] for c in counts if c["placeholders"] and not c["drafts"]]
    english = next((c["drafts"] for c in counts if c["language"] == "English"), 0)
    assignees = [f'{LANG_LABEL.get(c["language"], c["language"])}: {c["assignee"]}'
                 for c in counts if c["assignee"]]
    g, sh, tests = git_stats(), shelter_stats(), test_count()
    total, approved = len(rows), sum(c["approved"] for c in counts)
    def label(xs):
        names = [LANG_LABEL.get(x, x) for x in xs]
        return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    tasks = [
        {"task": "Shelter list",
         "ai": "An AI assistant (Claude) compiled the 2026 shelter list from county press "
               "releases and news reports: site name, address, event, date and pet policy, "
               f"with the source URL on every row ({n(sh['rows'])} rows). News reports were then "
               f"matched to official county releases: {n(sh['official_rows'])} of "
               f"{n(sh['rows'])} rows now cite an official county source.",
         "people": "A team member reviewed the table and read the county pages that block "
                   "automated tools (2026-10-27). Open code then grouped, located and "
                   "hazard-checked the sites.",
         "evidence": [["county_shelter_activations.csv on GitHub", LINKS["shelters"]]]},
        {"task": "Data discovery",
         "ai": "Datatrove's AI discovery chat found the current FEMA National Risk Index "
               "(v1.20) Census-area layers and field names, the HHS emPOWER county fields, "
               "and Census tables and download routes.",
         "people": "The team downloaded every dataset from its official source, checked the "
                   "field names and recorded each URL and fetch date.",
         "evidence": [["Sources (PLAN.md §3)", LINKS["sources"]]]},
        {"task": "Software",
         "ai": "Most of the code and tests were written with an AI coding assistant "
               "(Claude / Claude Code).",
         "people": "The team reviewed, ran and committed every change. "
                   f"{n(g['commits'])} commits, {n(g['coauthored'])} of them co-authored by "
                   f"Claude; {n(tests)} automated tests.",
         "evidence": [["Commit history on GitHub", LINKS["commits"]]]},
        {"task": "Multilingual messages",
         "ai": f"AI drafted {n(english)} English source messages and translations into "
               f"{len(translated)} languages ({label(translated)}). It made no drafts for "
               f"{label(human)}.",
         "people": f"Approved: {n(approved)} of {n(total)} messages. Every translation needs "
                   f"a native-speaker reviewer"
                   + (f" (assigned: {'; '.join(assignees)})" if assignees else "")
                   + f"; {label(human)} need human translators.",
         "evidence": [["Messages tab", "#messages"], ["Message files on GitHub", LINKS["messages"]]]},
    ]
    return {"tasks": tasks, "not_done": NOT_DONE, "message_counts": counts,
            "messages_total": total, "messages_approved": approved,
            "translated_languages": translated, "human_translation_languages": human,
            "commits": g["commits"], "coauthored": g["coauthored"], "head": g["head"],
            "tests": tests, "repo": REPO,
            "counted_note": "Counts are computed when the site is built, from the message "
                            "files and the repository history"
                            + (f" up to commit {g['head']}" if g["head"] else "") + "."}


def bundle_messages(rows: list | None = None) -> list:
    """Message rows for the app, every stored field kept as-is (plus display helpers)."""
    rows = load_messages() if rows is None else rows
    keep = ("message_id", "hazard", "trigger", "timing", "channel", "language", "text", "status",
            "translated_by", "review_assignee", "reviewed_by", "review_date", "approved", "notes",
            "file")
    out = []
    for r in rows:
        m = {k: r.get(k, "") for k in keep}
        m["phase"] = PHASES.get(r["message_id"].rsplit("-", 1)[-1], r["timing"])
        m["lang"] = LANG_TAG.get(r["language"], "")
        m["language_label"] = LANG_LABEL.get(r["language"], r["language"])
        out.append(m)
    return out
