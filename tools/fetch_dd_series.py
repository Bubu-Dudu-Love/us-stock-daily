# -*- coding: utf-8 -*-
"""拉取当日「个股深读」卡片标的的 Yahoo Finance 真实日线，断言末根收盘价与日报一致后
写入按日独立的 dd-series-<date>.js（不进 market_data.js 共享文件——深读标的逐日不同，
不该跟 4 大指数那种长期累积序列混在一起）。建站时该文件随当日 HTML 一并 <script src> 引入。

用法: python3 fetch_dd_series.py <YYYY-MM-DD> <TICKER1:EXPECT1> [<TICKER2:EXPECT2> ...]
示例: python3 fetch_dd_series.py 2026-06-25 AAPL:275.11 AMAT:668.00
"""
import json, os, subprocess, sys, urllib.parse
from datetime import datetime, timezone, timedelta

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def fetch_one(sym, cutoff):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           + urllib.parse.quote(sym) + "?range=1y&interval=1d")
    raw = subprocess.run(["curl", "-s", "--max-time", "30", "-H", f"User-Agent: {UA}", url],
                         capture_output=True, text=True, check=True).stdout
    r = json.loads(raw)["chart"]["result"][0]
    off = r["meta"]["gmtoffset"]
    q = r["indicators"]["quote"][0]
    dates, closes = [], []
    for i, t in enumerate(r["timestamp"]):
        d = datetime.fromtimestamp(t, tz=timezone(timedelta(seconds=off))).strftime("%Y-%m-%d")
        if d > cutoff:
            continue
        c = q["close"][i]
        if c is None:
            continue
        dates.append(d)
        closes.append(round(c, 2))
    return dates, closes


def main():
    if len(sys.argv) < 3:
        print("用法: python3 fetch_dd_series.py <YYYY-MM-DD> <TICKER1:EXPECT1> [<TICKER2:EXPECT2> ...]")
        sys.exit(2)
    cutoff = sys.argv[1]
    pairs = [a.split(":") for a in sys.argv[2:]]

    out = {}
    for sym, expect_str in pairs:
        expect = float(expect_str)
        dates, closes = fetch_one(sym, cutoff)
        assert dates and dates[-1] == cutoff, f"{sym}: 最后交易日 {dates[-1] if dates else '无数据'} != {cutoff}"
        last = closes[-1]
        assert abs(last - expect) <= expect * 0.001, \
            f"{sym}: 收盘 {last} 与日报 {expect} 偏差>0.1% —— 停止构建"
        out[sym] = {"dates": dates, "closes": closes}
        print(f"OK {sym}: {len(dates)} 根K线, 末根 {dates[-1]} close={last}")

    site_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dst = os.path.join(site_dir, f"dd-series-{cutoff}.js")
    with open(dst, "w", encoding="utf-8") as f:
        f.write(f"// 个股深读卡日线数据 · Yahoo Finance v8 chart API · 按日独立，不与 market_data.js 共享 · 末根 {cutoff} 收盘\n")
        f.write("const DD_SERIES=" + json.dumps(out, separators=(",", ":")) + ";\n")
    print("written ->", dst)


if __name__ == "__main__":
    main()
