#!/usr/bin/env python3
"""Snapshot Yahoo headlines for every symbol shortly after the US open.

Runs ~10 minutes after the open (before most opening-range entries), so the
headlines that came out before each entry are still in Yahoo's short feed.
Saves news/<New York date>.json. Re-running the same day merges, never duplicates.
Uses the skill's own news module (trader-news/news.py), Yahoo only, no keys.

  python3 news_snapshot.py
  python3 news_snapshot.py --offline DIR   # test with saved yahoo-<SYM>.xml files
"""
import argparse
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "trader-news"))
import news  # noqa: E402  (the skill's engine, unchanged)

LOOKBACK_HOURS = 24


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline")
    ap.add_argument("--now", help="UTC time, e.g. 2026-12-01T14:40 (testing)")
    a = ap.parse_args()

    now = (dt.datetime.fromisoformat(a.now).replace(tzinfo=dt.timezone.utc) if a.now
           else dt.datetime.now(dt.timezone.utc))
    day = news.to_eastern(now).date().isoformat()
    with open(os.path.join(HERE, "symbols.txt"), encoding="utf-8") as fh:
        syms = [s.strip().upper() for s in fh if s.strip() and not s.startswith("#")]

    fetcher = news.Fetcher(offline=a.offline, pause=1.0)
    items, errors = [], []
    for s in syms:
        try:
            got = news.parse_rss(fetcher.get(news.YAHOO % news.yahoo_symbol(s), "yahoo-%s.xml" % s), s)
        except news.NewsError as e:
            errors.append("%s: %s" % (s, e))
            continue
        items += news.tag(got, {s: None})

    os.makedirs(os.path.join(HERE, "news"), exist_ok=True)
    path = os.path.join(HERE, "news", day + ".json")
    old = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            old = json.load(fh)
    seen = {(o["ticker"], o["id"]) for o in old}
    cutoff = now - dt.timedelta(hours=LOOKBACK_HOURS)
    added = 0
    for it in items:
        if not it["time"] or it["time"] < cutoff or (it["ticker"], it["id"]) in seen:
            continue
        old.append({"ticker": it["ticker"], "id": it["id"], "title": it["title"],
                    "time": it["time"].strftime("%Y-%m-%dT%H:%M:%SZ"), "tags": it["tags"]})
        seen.add((it["ticker"], it["id"]))
        added += 1
    old.sort(key=lambda o: (o["ticker"], o["time"]))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(old, fh, ensure_ascii=False, indent=1)
    print("%s: saved %d new headlines (%d total) to %s" % (day, added, len(old), path))
    if errors:
        print("could not fetch:\n" + "\n".join(errors))
        if len(errors) == len(syms):
            sys.exit(1)


if __name__ == "__main__":
    main()
