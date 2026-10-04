#!/usr/bin/env python3
"""Build an .ics of USD High-impact + USD Holiday events from ForexFactory's weekly feed."""
import hashlib
import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
OUT_FILE = "usd-high-impact.ics"
ALERT_MINUTES = 10
EVENT_LENGTH_MIN = 15


def fetch_events():
    req = urllib.request.Request(FEED_URL, headers={"User-Agent": "Mozilla/5.0 (calendar-sync)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


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
        if ev.get("country") != "USD":
            continue
        impact = ev.get("impact")
        if impact not in ("High", "Holiday"):
            continue

        title = (ev.get("title") or "").strip()
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
        events = fetch_events()
    except Exception as exc:
        print(f"Feed fetch failed: {exc}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(events, list) or not events:
        print("Feed returned no events, keeping existing file.", file=sys.stderr)
        sys.exit(1)

    ics, count = build_ics(events)
    with open(OUT_FILE, "w", newline="") as f:
        f.write(ics)
    print(f"Wrote {count} events to {OUT_FILE}")


if __name__ == "__main__":
    main()
