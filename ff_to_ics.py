#!/usr/bin/env python3
"""Build an .ics of USD High-impact + USD Holiday events from ForexFactory's weekly feed.

Each run fetches the current week, merges it into events.json (a running store),
drops events older than the start of last month, and rebuilds the .ics from the store.
Past weeks therefore stay on the calendar instead of being overwritten.
"""
import hashlib
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
STORE_FILE = "events.json"
OUT_FILE = "usd-high-impact.ics"
ALERT_MINUTES = 10
EVENT_LENGTH_MIN = 15


def fetch_events():
    req = urllib.request.Request(FEED_URL, headers={"User-Agent": "Mozilla/5.0 (calendar-sync)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def load_store():
    if not os.path.exists(STORE_FILE):
        return []
    try:
        with open(STORE_FILE) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save_store(events):
    events = sorted(events, key=lambda e: (e["date"], e["title"]))
    with open(STORE_FILE, "w") as f:
        json.dump(events, f, indent=1)
        f.write("\n")


def cutoff_start(now):
    """First moment of the previous month (UTC)."""
    year, month = now.year, now.month - 1
    if month == 0:
        year, month = year - 1, 12
    return datetime(year, month, 1, tzinfo=timezone.utc)


def merge(stored, feed, now):
    """Return the new store: fresh week replaces its own window, older events stay."""
    parsed = []
    for ev in feed:
        try:
            parsed.append(datetime.fromisoformat(ev["date"]))
        except (KeyError, ValueError, TypeError):
            continue
    if not parsed:
        return stored

    # Window covered by this feed, in whole days, using the feed's own timezone.
    first, last = min(parsed), max(parsed)
    win_start = first.replace(hour=0, minute=0, second=0, microsecond=0)
    win_end = last.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)

    fresh = []
    for ev in feed:
        if ev.get("country") != "USD" or ev.get("impact") not in ("High", "Holiday"):
            continue
        fresh.append({
            "title": (ev.get("title") or "").strip(),
            "date": ev["date"],
            "impact": ev["impact"],
        })

    kept = []
    for ev in stored:
        try:
            dt = datetime.fromisoformat(ev["date"])
        except (KeyError, ValueError, TypeError):
            continue
        if win_start <= dt < win_end:
            continue  # superseded by the fresh feed (handles reschedules and removals)
        kept.append(ev)

    cutoff = cutoff_start(now)
    merged = []
    seen = set()
    for ev in kept + fresh:
        if datetime.fromisoformat(ev["date"]) < cutoff:
            continue
        key = (ev["title"], ev["date"], ev["impact"])
        if key in seen:
            continue
        seen.add(key)
        merged.append(ev)
    return merged


def esc(text):
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def utc_stamp(dt):
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_ics(events):
    now = utc_stamp(datetime.now(timezone.utc))
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//ff-usd-sync//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:USD High Impact News",
        "X-WR-CALDESC:ForexFactory USD high impact events and holidays",
        "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
        "X-PUBLISHED-TTL:PT12H",
    ]

    count = 0
    for ev in events:
        impact = ev["impact"]
        title = ev["title"]
        dt = datetime.fromisoformat(ev["date"])
        uid_src = f"{title}|{ev['date']}|{impact}"
        uid = hashlib.sha1(uid_src.encode()).hexdigest() + "@ff-usd-sync"

        lines += ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{now}"]

        if impact == "Holiday":
            day = dt.date()
            nxt = day + timedelta(days=1)
            lines += [
                f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}",
                f"DTEND;VALUE=DATE:{nxt.strftime('%Y%m%d')}",
                f"SUMMARY:{esc('US Holiday: ' + title)}",
                "TRANSP:TRANSPARENT",
            ]
        else:
            end = dt + timedelta(minutes=EVENT_LENGTH_MIN)
            lines += [
                f"DTSTART:{utc_stamp(dt)}",
                f"DTEND:{utc_stamp(end)}",
                f"SUMMARY:{esc('USD ' + title)}",
                "TRANSP:TRANSPARENT",
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{esc(title)}",
                f"TRIGGER:-PT{ALERT_MINUTES}M",
                "END:VALARM",
            ]

        lines.append("END:VEVENT")
        count += 1

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n", count


def main():
    try:
        feed = fetch_events()
    except Exception as exc:
        print(f"Feed fetch failed: {exc}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(feed, list) or not feed:
        print("Feed returned no events, keeping existing files.", file=sys.stderr)
        sys.exit(1)

    stored = load_store()
    merged = merge(stored, feed, datetime.now(timezone.utc))
    save_store(merged)

    ics, count = build_ics(merged)
    with open(OUT_FILE, "w", newline="") as f:
        f.write(ics)
    print(f"Store had {len(stored)} events, now {len(merged)}. Wrote {count} events to {OUT_FILE}")


if __name__ == "__main__":
    main()
