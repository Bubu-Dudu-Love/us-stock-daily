# -*- coding: utf-8 -*-
"""拉取 Yahoo Finance 真实日线，截断至 2026-06-11，断言收盘价与日报一致后输出 market_data.js"""
import json, os, subprocess, urllib.parse
from datetime import datetime, timezone, timedelta

TICKERS = [("GSPC", "^GSPC"), ("IXIC", "^IXIC"), ("DJI", "^DJI"), ("SMH", "SMH")]
EXPECT  = {"GSPC": 7394.30, "IXIC": 25809.66, "DJI": 50848.75, "SMH": 609.45}
CUTOFF  = "2026-06-11"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

out = {}
for key, sym in TICKERS:
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           + urllib.parse.quote(sym) + "?range=1y&interval=1d")
    raw = subprocess.run(["curl", "-s", "--max-time", "30", "-H", f"User-Agent: {UA}", url],
                         capture_output=True, text=True, check=True).stdout
    r = json.loads(raw)["chart"]["result"][0]
    off = r["meta"]["gmtoffset"]
    q = r["indicators"]["quote"][0]
    rows = []
    for i, t in enumerate(r["timestamp"]):
        d = datetime.fromtimestamp(t, tz=timezone(timedelta(seconds=off))).strftime("%Y-%m-%d")
        if d > CUTOFF: continue
        o, h, l, c, v = q["open"][i], q["high"][i], q["low"][i], q["close"][i], q["volume"][i]
        if None in (o, h, l, c): continue
        rows.append([d, round(o, 2), round(h, 2), round(l, 2), round(c, 2), v or 0])
    last = rows[-1]
    assert last[0] == CUTOFF, f"{key}: 最后交易日 {last[0]} != {CUTOFF}"
    assert abs(last[4] - EXPECT[key]) <= 0.01, \
        f"{key}: 收盘 {last[4]} 与日报 {EXPECT[key]} 不符 —— 停止构建"
    out[key] = rows
    print(f"OK {key}: {len(rows)} 根K线, 末根 {last[0]} close={last[4]}")

dst = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "market_data.js")
with open(dst, "w", encoding="utf-8") as f:
    f.write("// 数据来源：Yahoo Finance v8 chart API · 截至 2026-06-11 收盘 · 构建时断言与日报一致\n")
    f.write("const MARKET_DATA=" + json.dumps(out, separators=(",", ":")) + ";\n")
print("written ->", dst)
