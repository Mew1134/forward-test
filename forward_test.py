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
FIELDS = ["date", "symbol", "entry_time", "entry", "stop", "target", "outcome", "R"]


def load_symbols():
    with open(os.path.join(HERE, "symbols.txt"), encoding="utf-8") as fh:
        return [s.strip().upper() for s in fh if s.strip() and not s.startswith("#")]


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


def summarize(rows, state):
    trades = [r for r in rows if r["outcome"] != "no_signal"]
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
                  "", "| หุ้น | ไม้ | ได้กำไร | R เฉลี่ย |", "|---|---|---|---|"]
        for sym in sorted({t["symbol"] for t in trades}):
            ts = [t for t in trades if t["symbol"] == sym]
            g = sum(1 for t in ts if float(t["R"]) > 0)
            lines.append("| %s | %d | %d | %+.2f |" % (sym, len(ts), g, statistics.mean(float(t["R"]) for t in ts)))
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
                rows.append({"date": d, "symbol": sym, "entry_time": t["time"], "entry": t["entry"],
                             "stop": t["stop"], "target": t["target"], "outcome": t["outcome"], "R": t["R"]})
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
