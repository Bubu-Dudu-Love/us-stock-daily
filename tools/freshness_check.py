# -*- coding: utf-8 -*-
"""新鲜度/完整性校验：确认网页是当日真正重建的，而非中断后残留的旧页面拼接。
与 presentation_lint.py 同等地位，纳入 QA 硬门；只检查"是否是今天的内容"，不检查文风。
用法: python freshness_check.py <YYYY-MM-DD> [html路径] [md路径]
退出码非 0 = 不通过。
背景：2026-06-25 因 session usage limit 致自动续建反复失败，半成品(CUTOFF 误为前一日、
个股深读卡/关键人物/页脚仍是前一日内容)在结构/lint/node-check 全通过的情况下被手动发布——
四件套全是机械检查，没有任何一项验证"内容是不是今天的"，故补此项。
"""
import re, sys, os, glob

SITE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 网站/


def check(date, html_path=None, md_path=None):
    html_path = html_path or os.path.join(SITE_DIR, f"{date}.html")
    md_path = md_path or os.path.join(
        os.path.dirname(SITE_DIR), "美股日报", f"美股日报_{date}.md")

    html = open(html_path, encoding="utf-8").read()
    bad = []

    # ① CUTOFF JS 变量（决定 MARKET_DATA 截断到哪一天，错了图表会全部停在前一日）
    m = re.search(r'var CUTOFF="([\d-]+)"', html)
    if not m or m.group(1) != date:
        bad.append(f"CUTOFF 变量={m.group(1) if m else '未找到'}，应为 {date}")

    # ② 页脚「美股日报 · 日期 · Claude Code 生成」
    m = re.search(r'finale-gen">美股日报 · ([\d-]+) ·', html)
    if not m or m.group(1) != date:
        bad.append(f"finale-gen 日期戳={m.group(1) if m else '未找到'}，应为 {date}")

    # ③ 跑马灯「YYYY-MM-DD 美东收盘」
    m = re.search(r'(\d{4}-\d{2}-\d{2}) 美东收盘', html)
    if not m or m.group(1) != date:
        bad.append(f"跑马灯日期标签={m.group(1) if m else '未找到'}，应为 {date}")

    # ④ 「数据截至 ... 收盘」文字日期
    y, mo, d = date.split("-")
    expect_cn = f"{y} 年 {int(mo)} 月 {int(d)} 日"
    for m in re.finditer(r'数据截至 ([^<]+?)收盘', html):
        if expect_cn not in m.group(1):
            bad.append(f"「数据截至」日期={m.group(1).strip()}收盘，应含「{expect_cn}」")

    # ⑤ 个股深读卡 ticker 集合 vs md「今日 N 只：X · Y」标题（最能命中"整段抄前一天"事故）
    if os.path.exists(md_path):
        md = open(md_path, encoding="utf-8").read()
        m = re.search(r'个股深读（今日\s*\d+\s*只[：:]\s*([^）)]+)）', md)
        if m:
            ticker_part = m.group(1).split("——")[0]  # 「——主线两端」之类的描述语在右侧，先切掉避免误抓
            md_tickers = set(re.findall(r'\b[A-Z]{2,6}\b', ticker_part))
            html_tickers = set(re.findall(r'dd-tkr">([A-Z]{2,6})', html))
            if md_tickers != html_tickers:
                bad.append(f"个股深读卡 ticker 不一致：md={sorted(md_tickers)} html={sorted(html_tickers)}")
        else:
            print("（md 未找到「个股深读（今日 N 只」标题，跳过 ⑤ 项，不计入失败）")
    else:
        print(f"（md 文件不存在：{md_path}，跳过 ⑤ 项，不计入失败）")

    # ⑥ 重点个股 spot-strip 首条涨幅 % 须与前一期不同
    #    旧版只看 md 最大涨幅 ticker（跌日无 **TICKER +X%** 格式则整段跳过），改为直接比对 HTML 前后期
    #    此处只校验 sp-num 中第一个涨跌数字与前一期不同即可；完整 ticker 校验见 ⑦ 倒推锚点
    # （不再从 md 提取 md_gains，避免因跌日 md 无 bold-gain 格式而整项静默跳过）

    # ⑦ 关键文字锚点须与前一期不同（倒推：从页面底部往上逐节扫，全部报出、不短路）
    #    顺序：finale(底) → VI重点个股 → II大盘总览 → hero(顶)
    #    任意一节相同即说明该节未更新；多节相同可推断 session 在哪一步中断
    prev_cands = sorted(glob.glob(os.path.join(SITE_DIR, "????-??-??.html")))
    prev_cands = [p for p in prev_cands if os.path.basename(p) < f"{date}.html"]
    if prev_cands:
        prev_html = open(prev_cands[-1], encoding="utf-8").read()
        prev_label = os.path.basename(prev_cands[-1]).replace(".html", "")

        def _snap(pat, src, strip_tags=False):
            m = re.search(pat, src, re.DOTALL)
            if not m:
                return None
            s = m.group(1).strip()
            return re.sub(r'<[^>]+>', ' ', s).strip() if strip_tags else s

        anchors = [
            # (描述,                              正则,                                                   剥tag)
            ("finale-title（一句话定调）",         r'finale-title[^>]*>\s*([^<\n]{5,})',                  False),
            # 修复：旧版用 sp-tk 类（不存在），改为 sp-cap 抓第一个聚光灯描述文字
            ("VI 聚光灯首条（sp-cap）",            r'class="sp-cap">([^<]{10,60})',                       False),
            ("IV 宏观地缘 page-head desc",         r'id="page-macro".*?class="desc">([^<]{10,})',         False),
            ("II 大盘总览 核心读法",                r'核心读法[：:]</strong>(.*?)</div>',                   True),
            ("hero-theme-text（Hero主题句）",       r'hero-theme-text[^>]*>(.*?)</(?:div|p|h\d)>',        True),
        ]
        for name, pat, strip in anchors:
            cur = _snap(pat, html, strip)
            prev = _snap(pat, prev_html, strip)
            if cur and prev and cur == prev:
                bad.append(f"[⑦倒推] {name} 与 {prev_label} 相同（疑似该节未更新）：「{cur[:60]}」")

    # ⑧ 深读卡容器 id vs dd-series JS ticker 一致性
    #    场景：dd-series-YYYY-MM-DD.js 已更新为新日期标的，但 HTML 容器 id 仍是旧 ticker
    #    → buildDD() 调用 getElementById 找不到容器，图表静默不渲染
    m_src = re.search(r'<script src="(dd-series-[\d-]+\.js)">', html)
    if m_src:
        dd_js_path = os.path.join(SITE_DIR, m_src.group(1))
        if os.path.exists(dd_js_path):
            dd_js = open(dd_js_path, encoding="utf-8").read()
            series_keys = set(re.findall(r'"([A-Z]{2,6})":\{', dd_js))
            html_dd_ids = set(re.findall(r'id="dd-([A-Z]{2,6})"', html))
            if series_keys and html_dd_ids and series_keys != html_dd_ids:
                bad.append(
                    f"⑧ 深读卡容器 id {sorted(html_dd_ids)} 与 dd-series JS ticker "
                    f"{sorted(series_keys)} 不一致（深读卡未随 dd-series 一起更新）")

    # ⑨ 关键人物节（#page-people）不应出现前一日的 M/D 日期格式
    #    场景：从上一期模板复制后只改了正文，关键人物表格里的「7/2」仍为前一日
    if prev_cands:
        prev_date_str = os.path.basename(prev_cands[-1]).replace(".html", "")
        _, prev_mo2, prev_d2 = prev_date_str.split("-")
        prev_md_fmt = f"{int(prev_mo2)}/{int(prev_d2)}"   # e.g. "7/2"
        people_m = re.search(r'id="page-people"(.*?)(?=id="page-|</body>)', html, re.DOTALL)
        if people_m and prev_md_fmt in people_m.group(1):
            bad.append(
                f"⑨ 关键人物节仍含前一日日期「{prev_md_fmt}」（疑似从 {prev_label} 模板复制后未更新日期）")

    if bad:
        for b in bad:
            print(f"❌ {b}")
        print(f"\n新鲜度校验: {len(bad)} 处疑似残留旧内容")
        return 1
    print("新鲜度校验: 0 处疑似残留旧内容")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python freshness_check.py <YYYY-MM-DD> [html路径] [md路径]")
        sys.exit(2)
    sys.exit(check(sys.argv[1],
                    sys.argv[2] if len(sys.argv) > 2 else None,
                    sys.argv[3] if len(sys.argv) > 3 else None))
