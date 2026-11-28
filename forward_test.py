#!/usr/bin/env python3
"""Forward test (paper only, no orders) of the day-trader-skill opening-range breakout rule.

Rule (same as the skill's Time Machine history replay):
  buy when a 5-min bar closes above the 15-min opening range high,
  stop at the opening-range midpoint, target = 1R, else exit at the 4:00 PM close.

Run once a day after the US close. It only uses each day's bars in time order,
so judging the day after the close gives the same result as watching it live.

  python3 forward_test.py                 # fetch from Yahoo, update results
  python3 forward_test.py --offline DIR   # test with saved <SYM>-60d5m.json(.gz) files
"""
import argparse
import csv
import datetime
import json
import re
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "trader-timemachine"))
import timemachine as tm  # noqa: E402  (the skill's own engine, unchanged)

RULE = {"setup": "orb", "or_minutes": 15, "stop_rule": "or_mid", "target_r": 1.0}
LAST_BAR = tm.SESSION_BARS - 1          # exit at the 4:00 PM close
RESULTS = os.path.join(HERE, "results.csv")
STATE = os.path.join(HERE, "state.json")
SUMMARY = os.path.join(HERE, "SUMMARY.md")
FIELDS = ["date", "symbol", "entry_time", "entry", "stop", "target", "outcome", "R", "news_count", "news_tags"]
NEWS_DIR = os.path.join(HERE, "news")
NEWS_LOOKBACK = datetime.timedelta(hours=24)
_news_cache = {}
# "ETF X bought/sold stock Y" flow reports: daily filler on every big ticker, not news.
ETF_FLOW = re.compile(r"(\bETFs?\b|\b(Trust|ETF|Fund)\b.*\([A-Z]{2,5}\)|\([A-Z]{2,5}\) (Buys|Sells|Adds)|^What .+ (Bought|Sold):)", re.I)
ETF_ACT = re.compile(r"\b(Bought|Buys|Buy|Sells|Sold|Adds?|Add to|Buying|Selling|Inflows?|Outflows?)\b", re.I)


def is_etf_flow(title):
    return bool(ETF_FLOW.search(title) and ETF_ACT.search(title))


def news_before(day, sym, entry_time):
    """Tagged headlines (earnings, analyst, deal...) for sym, saved by news_snapshot.py, that
    came out in the 24 hours before the entry; ETF-flow filler is skipped.
    ("", "") when that day has no snapshot (unknown, left out of the comparison)."""
    if day not in _news_cache:
        path = os.path.join(NEWS_DIR, day + ".json")
        _news_cache[day] = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else None
    items = _news_cache[day]
    if items is None:
        return "", ""
    local = datetime.datetime.strptime(day + " " + entry_time, "%Y-%m-%d %I:%M %p")
    entry = tm.eastern_to_utc(local)
    hits = [it for it in items if it["ticker"] == sym and
            it["tags"] and not is_etf_flow(it["title"]) and
            entry - NEWS_LOOKBACK <= datetime.datetime.strptime(it["time"], "%Y-%m-%dT%H:%M:%SZ") < entry]
    tags = sorted({t for it in hits for t in it["tags"]})
    return str(len(hits)), "|".join(tags)


def _read_list(name):
    path = os.path.join(HERE, name)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [s.strip().upper() for s in fh if s.strip() and not s.startswith("#")]


def load_symbols():
    """Main watchlist (symbols.txt) first, then the experimental group (symbols_extra.txt)."""
    main = _read_list("symbols.txt")
    return main + [s for s in _read_list("symbols_extra.txt") if s not in main]


def load_results():
    if not os.path.exists(RESULTS):
        return []
    with open(RESULTS, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def save_results(rows):
    rows.sort(key=lambda r: (r["date"], r["symbol"]))
    with open(RESULTS, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def load_state():
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def _row(label, ts):
    if not ts:
        return "| %s | 0 | - | - | - |" % label
    n = len(ts)
    return "| %s | %d | %.0f%% | %.0f%% | %+.2f |" % (
        label, n, 100.0 * sum(1 for t in ts if float(t["R"]) > 0) / n,
        100.0 * sum(1 for t in ts if t["outcome"] == "target") / n,
        statistics.mean(float(t["R"]) for t in ts))


def news_section(trades):
    known = [t for t in trades if (t.get("news_count") or "") != ""]
    out = ["", "## ข่าวก่อนเข้าเทรด (24 ชม. ก่อนเวลาเข้า, Yahoo, เฉพาะข่าวที่มีป้ายประเภท ไม่นับข่าว ETF ซื้อขาย)", ""]
    if not known:
        return out + ["ยังไม่มีไม้ที่มีข้อมูลข่าว (เริ่มเก็บข่าวตั้งแต่รอบ 21:40 น. แรก)"]
    out += ["| กลุ่ม | ไม้ | ได้กำไร | ถึงเป้า | R เฉลี่ย |", "|---|---|---|---|---|",
            _row("ไม่มีข่าว", [t for t in known if t["news_count"] == "0"]),
            _row("มีข่าว", [t for t in known if t["news_count"] != "0"])]
    for tag in sorted({g for t in known for g in (t.get("news_tags") or "").split("|") if g}):
        out.append(_row("มีข่าว " + tag, [t for t in known if tag in (t.get("news_tags") or "").split("|")]))
    out += ["", "ไม้ที่ยังไม่มีข้อมูลข่าว (ก่อนเริ่มเก็บ) ไม่นับในตารางนี้ | ตัวอย่างน้อยกว่า ~30 ไม้ต่อกลุ่ม ยังสรุปไม่ได้"]
    return out


def _per_stock(trades):
    out = ["| หุ้น | ไม้ | ได้กำไร | R เฉลี่ย |", "|---|---|---|---|"]
    for sym in sorted({t["symbol"] for t in trades}):
        ts = [t for t in trades if t["symbol"] == sym]
        g = sum(1 for t in ts if float(t["R"]) > 0)
        out.append("| %s | %d | %d | %+.2f |" % (sym, len(ts), g, statistics.mean(float(t["R"]) for t in ts)))
    return out


def summarize(rows, state):
    main_syms = set(_read_list("symbols.txt"))
    alltrades = [r for r in rows if r["outcome"] != "no_signal"]
    trades = [r for r in alltrades if r["symbol"] in main_syms]
    extra = [r for r in alltrades if r["symbol"] not in main_syms]
    days = state.get("days", [])
    lines = ["# ผลทดสอบเดินหน้า (forward test)", "",
             "กฎ: ทะลุกรอบ 15 นาทีแรก, stop กึ่งกลางกรอบ, เป้า 1R | เริ่ม %s | อัปเดต %s UTC" % (
                 state.get("start_date", "-"), datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")), ""]
    if not trades:
        lines.append("ยังไม่มีไม้เทรด (ตรวจไปแล้ว %d วัน)" % len(days))
    else:
        n = len(trades)
        tgt = sum(1 for t in trades if t["outcome"] == "target")
        stp = sum(1 for t in trades if t["outcome"] == "stop")
        cls = n - tgt - stp
        green = sum(1 for t in trades if float(t["R"]) > 0)
        avg = statistics.mean(float(t["R"]) for t in trades)
        lines += ["| | ไม้ | % |", "|---|---|---|",
                  "| ถึงเป้ากำไร | %d | %.1f%% |" % (tgt, 100.0 * tgt / n),
                  "| โดน stop | %d | %.1f%% |" % (stp, 100.0 * stp / n),
                  "| ปิดตอนตลาดปิด | %d | %.1f%% |" % (cls, 100.0 * cls / n),
                  "| **ได้กำไร (R > 0)** | **%d** | **%.1f%%** |" % (green, 100.0 * green / n),
                  "", "รวม %d ไม้ จาก %d วันทำการ | กำไรเฉลี่ย %+.3fR ต่อไม้ (ยังไม่หักค่าธรรมเนียม)" % (n, len(days), avg),
                  ""] + _per_stock(trades)
    lines += news_section(trades)
    extra_syms = [x for x in _read_list("symbols_extra.txt") if x not in main_syms]
    if extra_syms or extra:
        lines += ["", "## กลุ่มทดลอง (%s) ไม่นับรวมในผลหลักด้านบน" % ", ".join(extra_syms or sorted({t["symbol"] for t in extra})), ""]
        if extra:
            avg = statistics.mean(float(t["R"]) for t in extra)
            green = sum(1 for t in extra if float(t["R"]) > 0)
            lines += ["รวม %d ไม้ | ได้กำไร %.0f%% | กำไรเฉลี่ย %+.3fR ต่อไม้" % (len(extra), 100.0 * green / len(extra), avg), ""]
            lines += _per_stock(extra)
        else:
            lines.append("ยังไม่มีไม้เทรด")
    with open(SUMMARY, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", help="folder with <SYM>-60d5m.json(.gz) files, for testing")
    a = ap.parse_args()

    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)  # engine uses naive UTC
    rows = load_results()
    done = {(r["date"], r["symbol"]) for r in rows}
    state = load_state()
    errors = []

    for i, sym in enumerate(load_symbols()):
        try:
            if a.offline:
                text = tm.read_offline(a.offline, sym)
                as_of = datetime.datetime(2100, 1, 1)
            else:
                if i:
                    time.sleep(3)
                text = tm.fetch_chart(sym)
                as_of = now
            _, bars, _ = tm.parse_bars(tm.chart_result(text, sym), as_of)
            full, _ = tm.full_sessions(tm.split_sessions(bars), "9999-12-31")
        except tm.TMError as e:
            errors.append("%s: %s" % (sym, e))
            continue
        if not full:
            continue
        # First run: start from the latest full session only (a forward test, not a backtest).
        state.setdefault("start_date", full[-1][0])
        for d, D in full:
            if d < state["start_date"] or (d, sym) in done:
                continue
            state.setdefault("days", [])
            if d not in state["days"]:
                state["days"].append(d)
            h = tm.history_replay([(d, D)], RULE, LAST_BAR, "buy")
            if not h["trades"]:
                rows.append({"date": d, "symbol": sym, "entry_time": "", "entry": "", "stop": "",
                             "target": "", "outcome": "no_signal", "R": "0"})
            for t in h["trades"]:
                nc, nt = news_before(d, sym, t["time"])
                rows.append({"date": d, "symbol": sym, "entry_time": t["time"], "entry": t["entry"],
                             "stop": t["stop"], "target": t["target"], "outcome": t["outcome"], "R": t["R"],
                             "news_count": nc, "news_tags": nt})
            done.add((d, sym))

    state["days"] = sorted(state.get("days", []))
    save_results(rows)
    with open(STATE, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=1)
    summarize(rows, state)
    if errors:
        print("\nดึงข้อมูลไม่ได้:\n" + "\n".join(errors))
        if len(errors) == len(load_symbols()):
            sys.exit(1)


if __name__ == "__main__":
    main()
