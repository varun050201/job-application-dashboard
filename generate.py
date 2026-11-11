#!/usr/bin/env python3
"""Generate data.json for the job-application dashboard from the pipeline
ledger + park registry. Strips personal details (emails, phones, street
addresses, ZIPs, local file paths, secure-entry links) before anything is
published. Run: python3 generate.py  (writes data.json next to this file)
"""
import json
import os
import re
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

HOME = os.path.expanduser("~")
LEDGER = os.path.join(HOME, "workspace/job_applications/ledger.md")
REGISTRY = os.path.join(HOME, "workspace/goals/job-application-pipeline/hidden_files/park_registry.md")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")
ET = ZoneInfo("America/New_York")

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE_RE = re.compile(r"(?<!\d)(\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)")
# Digit-boundary guards (2026-11-05 R&D intraday): without them the pattern
# matched the first 10 digits of 12-19 digit req/URL IDs (ByteDance,
# Meta, Google) and published them mangled as "[phone]094984986". The
# guards only stop matches INSIDE a longer digit run; every real phone
# format still masks (see hidden_files/rnd_20261105_sanitize_test.py).
ADDR_RE = re.compile(r"\d{1,5}\s+[A-Z][\w ]*?\b(?:Rd|Road|St|Street|Ave|Avenue|Blvd|Ln|Dr|Drive)\b[^,;|]*", re.I)
APT_RE = re.compile(r"\bApt\.?\s*\w+", re.I)
ZIP_RE = re.compile(r"\b\d{5}(?:-\d{4})?\b")
URL_RE = re.compile(r"https?://[^\s)>\]]+")


def sanitize(text):
    text = EMAIL_RE.sub("[email]", text)
    text = PHONE_RE.sub("[phone]", text)
    text = ADDR_RE.sub("[address]", text)
    text = APT_RE.sub("[apt]", text)
    text = ZIP_RE.sub("[zip]", text)
    text = re.sub(r"~?/[\w./-]+", "", text)  # local paths
    return re.sub(r"\s+", " ", text).strip()


def first_url(row):
    for u in URL_RE.findall(row):
        if "agent.meta.ai" in u or "credential" in u:
            continue
        return u.rstrip(".,")
    return ""


def parse_date(text):
    m = re.search(r"20\d{2}-\d{2}-\d{2}", text or "")
    return m.group(0) if m else ""


def extract_deadline(row):
    # Only dates that FOLLOW a deadline keyword (never posted/reset/expiry dates).
    # Prefer operative close words (closes/deadline) over "end date" when both appear.
    pat = (r"(deadline|closes?|closing|end date|apply before|last date)[^|\n]{0,40}?"
           r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:,?\s+20\d{2})?|\d{1,2}/\d{1,2}/(?:20\d{2}|\d{2}))")
    matches = list(re.finditer(pat, row, re.I))
    if not matches:
        return ""
    def rank(m):
        return 0 if m.group(1).lower().startswith(("clos", "deadline", "apply", "last")) else 1
    m = sorted(matches, key=rank)[0]
    raw = m.group(2)
    mm = re.match(r"([A-Za-z]+)\.?\s+(\d{1,2})(?:,?\s+(20\d{2}))?", raw)
    if mm:
        mon = MONTHS[mm.group(1).lower()[:3]]
        year = int(mm.group(3)) if mm.group(3) else (2026 if mon >= 10 else 2027)
        return f"{year:04d}-{mon:02d}-{int(mm.group(2)):02d}"
    mm = re.match(r"(\d{1,2})/(\d{1,2})/(20\d{2}|\d{2})", raw)
    if mm:
        year = int(mm.group(3)) if len(mm.group(3)) == 4 else 2000 + int(mm.group(3))
        return f"{year:04d}-{int(mm.group(1)):02d}-{int(mm.group(2)):02d}"
    return ""


def classify(status):
    s = status.strip()
    if s.startswith("OPEN — with Varun") or s.startswith("OPEN — WITH") or \
            "WITH-VARUN" in s[:60] or s.startswith("OPEN — Tier 3") or \
            s.startswith("OPEN — needs") or s.startswith("OPEN — NEEDS"):
        return "human_gate"
    if s.startswith("OPEN — Tier 1") or s.startswith("OPEN — Tier 2") or \
            s.startswith("OPEN — re-dispatch") or s.startswith("OPEN — credential-pending") or \
            s.startswith("OPEN — reset-exhausted"):
        return "pipeline_owned"
    if s.startswith("OPEN — quota"):
        return "quota"
    if s.startswith("OPEN — portal"):
        return "portal_limit"
    if s.startswith("OPEN — reset-pending"):
        return "watch_reset"
    if s.startswith("OPEN"):
        return "human_gate"
    if s.startswith("RESOLVED"):
        return "resolved"
    if s.startswith("CLOSED") or s.startswith("KILLED"):
        return "closed"
    if s.startswith("HOLD"):
        return "hold"
    if s.startswith("SUPERSEDED"):
        return "superseded"
    return "other"


def main():
    # ---- ledger: submissions ----
    subs = []
    with open(LEDGER, encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("- SUBMITTED"):
                body = line[len("- SUBMITTED:"):].strip()
            elif line.startswith("SUBMITTED:"):
                # closeout.py format (no dash prefix) — same verified
                # submissions, missed by the dash-only check until 2026-11-11
                body = line[len("SUBMITTED:"):].strip()
            else:
                continue
            company = body.split("—")[0].strip()
            mreq = re.search(r"req ([A-Za-z0-9_.\-]+)", body)
            if not mreq:
                # closeout format: "(10540973, 2026-11-11) phase-N"
                mreq = re.search(r"\((\d[\w.\-]*),\s*20\d{2}-", body)
            # email confirmation only when the line cites an actual Gmail
            # confirmation message (ID + thank-you/received wording), not a
            # mere Gmail duplicate check or a portal confirmation note.
            email_conf = bool(re.search(r"Gmail 1a[0-9a-f]{6,}", body)) and \
                ("Thank you" in body or "received your" in body or "we have received" in body)
            subs.append({
                "company": company,
                "role": body.split("—")[1].split("(")[0].strip() if "—" in body else "",
                "req": mreq.group(1) if mreq else "",
                "date": parse_date(body),
                "email_confirmed": email_conf,
            })
    daily = Counter(s["date"] for s in subs if s["date"])
    daily_list = [{"date": d, "count": daily[d]} for d in sorted(daily)]

    # today's verified email confirmations (checked in the work inbox)
    today = datetime.now(ET).strftime("%Y-%m-%d")
    email_yes_today = {"Mozilla", "Tesla", "Boingo", "iSeatz", "Ingram Content Group",
                       "Legacy Community Health", "Insight Enterprises"}
    today_rows = []
    for s in subs:
        if s["date"] == today:
            row = dict(s)
            row["email_confirmed"] = s["company"] in email_yes_today or s["email_confirmed"]
            today_rows.append(row)

    # ---- registry: parks ----
    buckets = Counter()
    queue = {"human_gate": [], "pipeline_owned": [], "quota": [], "portal_limit": [],
             "watch_reset": [], "hold": [], "resolved": [], "closed": [], "superseded": [], "other": []}
    with open(REGISTRY, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("- Palantir"):
                queue["human_gate"].append({
                    "role": "Palantir — Incident Management Engineer", "req": "b72abc17",
                    "parked": "2026-10-24", "deadline": "", "deadline_passed": False,
                    "blocker": "AI notetaker consent question needs your own Yes/No word.",
                    "link": ""})
                buckets["human_gate"] += 1
                continue
            if not line.startswith("|"):
                continue
            parts = line.split("|")
            if len(parts) < 8:
                continue
            role = parts[1].strip()
            if role in ("Role", "") or set(role) <= set("- "):
                continue
            # status = last field that STARTS with a status keyword (robust
            # to rows with shifted columns); parked/blocker derive from it.
            STATUS_START = ("OPEN", "RESOLVED", "CLOSED", "KILLED", "HOLD", "SUPERSEDED")
            sidx = None
            for i in range(len(parts) - 1, 0, -1):
                if parts[i].strip().startswith(STATUS_START):
                    sidx = i
                    break
            if sidx is None:
                continue
            status = parts[sidx].strip()
            req = parts[2].strip()
            if sidx >= 6:
                parked, blocker = parts[3].strip(), parts[4].strip()
            else:
                parked, blocker = "", parts[3].strip()
            cat = classify(status)
            buckets[cat] += 1
            blocker_short = sanitize(blocker)
            if len(blocker_short) > 170:
                blocker_short = blocker_short[:170].rsplit(" ", 1)[0] + "…"
            dl = extract_deadline(line)
            queue[cat].append({
                "role": sanitize(role)[:110],
                "req": req[:60],
                "parked": parse_date(parked) or parse_date(line),
                "deadline": dl,
                "deadline_passed": bool(dl and dl < today),
                "blocker": blocker_short,
                "link": first_url(line),
            })

    def qsort(rows):
        future = sorted([r for r in rows if r["deadline"] and not r["deadline_passed"]],
                        key=lambda r: r["deadline"])
        none = sorted([r for r in rows if not r["deadline"]],
                      key=lambda r: r["parked"], reverse=True)
        past = sorted([r for r in rows if r["deadline_passed"]],
                      key=lambda r: r["deadline"])
        return future + none + past
    for k in queue:
        queue[k] = qsort(queue[k])

    data = {
        "generated_at_et": datetime.now(ET).strftime("%Y-%m-%d %H:%M ET"),
        "summary": {
            "total_submitted_ledger": len(subs),
            "today_submitted": len(today_rows),
            "human_gate": buckets["human_gate"],
            "watch_reset": buckets["watch_reset"],
            "pipeline_owned": buckets["pipeline_owned"],
            "quota": buckets["quota"],
            "portal_limit": buckets["portal_limit"],
            "hold": buckets["hold"],
            "resolved": buckets["resolved"],
            "closed": buckets["closed"],
            "registry_rows": sum(buckets.values()),
        },
        "daily": daily_list,
        "today": today_rows,
        "queue": queue,
        "notes": [
            "Counts come from the pipeline ledger (submissions) and the park registry (parked roles).",
            "Ledger submission counts are the verified floor: some run reports claimed more on certain days than ever got ledger lines.",
            "The human-gate queue is ordered deadline-first, then newest parked first. A row's deadline is read from its registry text and may be approximate.",
            "No personal details are published here: no email addresses, phone numbers, street addresses, or resume file paths.",
        ],
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    print("wrote", OUT)
    print(json.dumps(data["summary"], indent=1))


if __name__ == "__main__":
    main()
