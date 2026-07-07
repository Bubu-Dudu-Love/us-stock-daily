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

    # ⑥ 重点个股板块 spot-strip 最大涨幅 ticker 须与 md 5.1 节的最大涨幅 ticker 一致
    #    （最能命中"整板块复制未改"事故：md 最强是 IREN +13.1%，但 spot-strip 还写着 AAPL +4.84%）
    if os.path.exists(md_path):
        md_text = open(md_path, encoding="utf-8").read() if 'md' not in dir() else md
        # 从 md 5.1 重点个股小节取最大涨幅 ticker
        md_gains = re.findall(r'\*\*([A-Z]{2,6})\s*\+(\d+\.\d+)%\*\*', md_text)
        if md_gains:
            top_md = max(md_gains, key=lambda x: float(x[1]))
            top_md_tk, top_md_pct = top_md[0], float(top_md[1])
            # 从 HTML spot-strip 取最大涨幅 ticker
            sp_gains = re.findall(r'sp-num[^>]*style="color:var\(--green\)"[^>]*>\+(\d+\.\d+)%', html)
            if not sp_gains:
                sp_gains = re.findall(r'sp-num.*?\+(\d+\.\d+)%', html)
            if sp_gains:
                top_sp_pct = max(float(p) for p in sp_gains)
                # 允许 0.5pp 容差（数据来源格式化差异）
                if abs(top_sp_pct - top_md_pct) > 0.5:
                    bad.append(
                        f"重点个股 spot-strip 最大涨幅 {top_sp_pct}% 与 md 最大涨幅 {top_md_tk} {top_md_pct}% 不一致（疑似整板块未更新）")

    # ⑦ finale-title / hero-theme-text 须与前一期不同（防整段复制后未替换文字内容）
    prev_candidates = sorted(glob.glob(os.path.join(SITE_DIR, "????-??-??.html")))
    prev_candidates = [p for p in prev_candidates if os.path.basename(p) < f"{date}.html"]
    if prev_candidates:
        prev_html = open(prev_candidates[-1], encoding="utf-8").read()
        prev_label = os.path.basename(prev_candidates[-1]).replace(".html", "")
        # finale-title（一句话定调标题，纯文字）
        re_fin = r'finale-title[^>]*>\s*([^<\n]+)'
        mc = re.search(re_fin, html)
        mp = re.search(re_fin, prev_html)
        if mc and mp and mc.group(1).strip() == mp.group(1).strip():
            bad.append(f"finale-title 与 {prev_label} 完全相同：「{mc.group(1).strip()[:40]}」（疑似一句话定调未更新）")
        # hero-theme-text（可能含 <br>，先剥 tag 再比较）
        re_hero = r'hero-theme-text[^>]*>(.*?)</(?:div|p|h\d)>'
        mch = re.search(re_hero, html, re.DOTALL)
        mph = re.search(re_hero, prev_html, re.DOTALL)
        if mch and mph:
            cur_t = re.sub(r'<[^>]+>', ' ', mch.group(1)).strip()
            prev_t = re.sub(r'<[^>]+>', ' ', mph.group(1)).strip()
            if cur_t and prev_t and cur_t == prev_t:
                bad.append(f"hero-theme-text 与 {prev_label} 完全相同（疑似 Hero 主题句未更新）")

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
